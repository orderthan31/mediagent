from datetime import datetime, timezone
import logging
import math
import os
import shutil
import hashlib
from pathlib import Path
from contextlib import ExitStack
import time
from threading import Event
from concurrent.futures import ThreadPoolExecutor
from .resources import job_resources, resource_slot, gpu_slot, LIMITS
from video_service.queue_control import QueueControl, QUEUE_LOCK_ID

from video_service.locking import job_lock, JobBusyError, encoding_slot, wait_for_job_lock
from video_service.models import JobStatus, TERMINAL_STATUSES, utc_now_iso
from video_service.review import read_draft, write_draft
from video_service.repository import FilesystemJobRepository, JobNotFoundError
from video_service.storage import remove_path_inside, write_json_atomic, read_json
from video_service.workflows import workflow_plan
from video_service.artifacts import cue_digest, validate_cues as validate_input_cues
from video_service.subtitles import segments_to_srt, segment_subtitles
from video_service.sami import segments_to_sami
from video_service.timeline import TimelineSpan
from .packed_timeline import restore_segments
from video_service.transcript import filter_transcript_segments, TranscriptSegment
from .media import probe, extract_audio, preprocess_audio, encoding_args, select_encoder
from .process import run_process, Cancelled
from .providers import GeminiProvider
from .llm_trace import capture_calls
from .checkpoints import Checkpoints
from .completed_transcript import transcript_identity, load_completed_transcript, save_completed_transcript
from .content_block import block_details, BLOCKED_TEXT
from .sentence_transcription import transcription_prompt
from .transcription_queue import PartialTranscriptionError, PartialTranslationError
from .cleanup import collect_orphans
from .progress import encoding_progress
from video_service.config import load_environment
from video_service.llm_settings import LLMSettingsStore
from video_service.capacity import reserve_workspace
from .worker_storage import check_capacity as assert_capacity
from .shutdown import shutdown_signals, WorkerStopping
from .validation import validate_cues, validate_output, validate_decodable


class Worker:
    def __init__(self, repository, provider, stop=None, provider_factory=None):
        self.repository = repository
        self.provider = provider
        self.stop = stop if stop is not None else Event()
        self.provider_factory = provider_factory
        self._pool = None
        self._active = {}

    def check_stopping(self):
        if self.stop.is_set():
            raise WorkerStopping()

    def transition(self, job_id, status, **kwargs):
        def check_cancel():
            self.check_stopping()
            record = self.repository.read(job_id)
            if record.metadata.get("cancel_requested") or record.status == JobStatus.CANCELLED:
                raise Cancelled()
        with wait_for_job_lock(self.repository, job_id, check=check_cancel):
            metadata = {"stage_progress": None, "wait_reason": None, "wait_started_at": None,
                        "paid_operation_in_flight": False,
                        **kwargs.pop("metadata", {})}
            return self.repository.update_status(job_id, status, metadata=metadata, **kwargs)

    def cleanup(self, job_id, keep_output=False):
        root = self.repository.storage_root
        errors = []
        for name in (["input", "work"] if keep_output else ["input", "work", "output"]):
            try:
                remove_path_inside(root, self.repository.job_dir(job_id) / name)
            except OSError as exc:
                errors.append(f"{name}: {exc}")
        if errors:
            raise OSError("; ".join(errors))

    def process(self, job_id):
        repo = self.repository
        with ExitStack() as authorization_context, job_lock(repo, job_id, "execution"), job_resources(repo, job_id), capture_calls(repo.storage_root,
                repo.job_dir(job_id) / "work" / "llm" if repo.preserve_artifacts else None):
            with job_lock(repo, QUEUE_LOCK_ID), job_lock(repo, job_id):
                if self.stop.is_set():
                    return
                record = repo.read(job_id)
                if record.status != JobStatus.QUEUED:
                    return
                if QueueControl(repo.storage_root).read(record.metadata.get('owner_id'))['paused']:
                    return
                from video_service.execution_worker import legacy_execution
                from video_service.execution_authorization import AuthorizationConflict
                try:frozen_inputs=authorization_context.enter_context(legacy_execution(repo,record))
                except (AuthorizationConflict,FileNotFoundError,KeyError):
                    repo.update_status(job_id,JobStatus.FAILED,error="서버 실행 승인/고정 입력이 바뀌었거나 이미 입장한 실행입니다. 자동 재시도하지 않습니다.",metadata={"recovery_required":True,"execution_approval_required":True})
                    return
                repo.update_status(job_id, JobStatus.ANALYZING, metadata={"failure": None,
                    'recovery_policy_version': 1, 'recovery_required': False, 'wait_reason': None})
            last_heartbeat = 0
            last_progress = 0
            progress_path = None
            progress_duration = 0

            def check():
                nonlocal last_heartbeat, last_progress
                self.check_stopping()
                current = repo.read(job_id)
                if current.metadata.get("cancel_requested") or current.status == JobStatus.CANCELLED:
                    raise Cancelled()
                if progress_path is not None and time.monotonic() - last_progress >= 1:
                    fraction = encoding_progress(progress_path, progress_duration)
                    if fraction is not None:
                        try:
                            with job_lock(repo, job_id):
                                latest = repo.read(job_id)
                                latest.metadata["stage_progress"] = fraction
                                repo.save(latest)
                            last_progress = time.monotonic()
                        except JobBusyError:
                            pass
                if time.monotonic() - last_heartbeat > 5:
                    from .faceswap.runner import heartbeat_capabilities
                    heartbeat_capabilities(repo)
                    if record.metadata.get('faceswap_operation') in {'analyze_source', 'analyze_reference', 'preview'}:
                        # Admission already reserved the bounded preview workspace. Do
                        # not enumerate the entire host-mounted library per frame.
                        from video_service.capacity import assert_free_space
                        assert_free_space(repo.storage_root, int(os.getenv('MIN_FREE_SPACE_BYTES', str(50 * 1024**3))))
                    else:
                        assert_capacity(repo.storage_root,
                            int(os.getenv("VIDEO_SERVICE_QUOTA_BYTES", str(300 * 1024**3))),
                            int(os.getenv("MIN_FREE_SPACE_BYTES", str(50 * 1024**3))))
                    try:
                        with job_lock(repo, job_id):
                            repo.heartbeat(job_id)
                        last_heartbeat = time.monotonic()
                    except JobBusyError:
                        pass

            try:
                if record.metadata.get('faceswap_operation'):
                    from .faceswap.runner import execute
                    with gpu_slot(check, keep_preview=True):
                        execute(self, record, check)
                    return
                if self.provider_factory is not None:
                    self.provider = self.provider_factory(record.metadata.get('owner_id'))
                    preferences = getattr(self.provider, 'preferences', {})
                    with wait_for_job_lock(repo, job_id, check=check):
                        current = repo.read(job_id)
                        current.metadata['llm_settings'] = {key: preferences[key] for key in (
                            'transcription_model', 'translation_model', 'transcription_fallback_model',
                            'translation_fallback_model', 'translation_provider', 'translation_fallback_provider',
                            'transcription_provider', 'transcription_fallback_provider',
                            'fallback_on_error', 'fallback_on_block', 'revision') if key in preferences}
                        repo.save(current)
                work = repo.job_dir(job_id) / "work"
                work.mkdir(exist_ok=True)
                workflow = record.metadata.get('workflow', {})
                plan = workflow_plan(workflow.get('template', 'full'),
                    subtitle_input=bool(record.metadata.get('subtitle_input')),
                    subtitle_mode=record.options.subtitle_mode, audio_input=bool(record.metadata.get('audio_input')))
                stages = plan['stages']
                if hasattr(self.provider, 'validate_for_stages'):
                    self.provider.validate_for_stages(stages)
                encoder = None
                if not workflow:
                    with gpu_slot(check), encoding_slot(repo, int(os.getenv('MAX_ENCODING_JOBS', '1')), check):
                        encoder = select_encoder(work, check, video_codec=record.options.video_codec)
                selected = None
                selected_audio = None
                if record.metadata.get('audio_input'):
                    selected_audio = frozen_inputs.get('audio',repo.job_dir(job_id) / 'input/audio.wav')
                    with selected_audio.open('rb') as stream:
                        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                    if digest != record.metadata['audio_input']['sha256']:
                        raise ValueError('Audio snapshot integrity check failed')
                if record.metadata.get('subtitle_input'):
                    snapshot = read_json(frozen_inputs.get('subtitle',repo.job_dir(job_id) / 'input/subtitle.json'))
                    if cue_digest(snapshot['cues']) != record.metadata['subtitle_input']['sha256']:
                        raise ValueError('Subtitle snapshot integrity check failed')
                    selected = [TranscriptSegment.from_dict(c) for c in snapshot['cues']]
                source = frozen_inputs.get('source',repo.source_path(record)).resolve()
                checkpoints = Checkpoints(work, {"version": 1, "source_size": source.stat().st_size,
                    "source_mtime": source.stat().st_mtime_ns, "options": {key: value for key, value in record.options.to_dict().items()
                        if (key != "video_description" or value) and (key != "vad_mode" or value != "off")},
                    "stt": getattr(self.provider, "transcription_identity", getattr(self.provider, "transcription_model", None)),
                    "transcription_policy": transcription_prompt(record.options.source_language, 0),
                    "translation": getattr(self.provider, "translation_identity", getattr(self.provider, "translation_model", None)),
                    "filter_model": getattr(self.provider, "audio_filter_model", None),
                    "filter_enabled": os.getenv("VOCALIZATION_FILTER_ENABLED", "false")},
                    lambda size: assert_capacity(repo.storage_root,
                        int(os.getenv("VIDEO_SERVICE_QUOTA_BYTES", str(300 * 1024**3))),
                        int(os.getenv("MIN_FREE_SPACE_BYTES", str(50 * 1024**3))), additional=size))
                metadata = probe(source, work, check)
                videos = [stream for stream in metadata["streams"] if stream["codec_type"] == "video"]
                if not videos or ('extract_audio' in stages and not any(s["codec_type"] == "audio" for s in metadata["streams"])):
                    raise ValueError("Video and audio streams are required")
                if selected is not None:
                    validate_input_cues([s.to_dict() for s in selected], metadata['duration'])
                write_json_atomic(work / "metadata.json", metadata)
                reserve_workspace(repo, job_id, metadata["duration"],
                    int(os.getenv("VIDEO_SERVICE_QUOTA_BYTES", str(300 * 1024**3))),
                    int(os.getenv("MIN_FREE_SPACE_BYTES", str(50 * 1024**3))), check)
                languages = [record.options.target_language, *record.options.additional_languages]
                needs_review = False
                has_blocks = False
                if 'translate' not in stages and not ('encode' in stages and selected is not None):
                    languages = []
                if record.metadata.get("review_ready"):
                    from video_service.execution_worker import approved_review
                    draft = approved_review(repo, record)
                    subtitle_sets = {name: [TranscriptSegment.from_dict(cue) for cue in cues]
                        for name, cues in draft["tracks"].items()}
                elif plan['template'] == 'encode':
                    subtitle_sets = {'original': selected, 'translated': selected} if selected is not None else {}
                    if selected is not None:
                        for name in ['transcript', 'translated']:
                            write_json_atomic(work / (name + '.json'), [s.to_dict() for s in selected])
                else:
                    completed_identity = transcript_identity(source, record)
                    from video_service.execution_authorization import active_authorization
                    completed = load_completed_transcript(work, completed_identity) if 'transcribe' in stages and active_authorization() is None else None
                    if completed is not None:
                        segments = [TranscriptSegment.from_dict(item) for item in completed]
                        write_json_atomic(work / "transcript.json", completed)
                        self.transition(job_id, JobStatus.FILTERING_TRANSCRIPT, metadata={
                            "transcription_reused": True, "transcription_progress": None})
                    elif 'transcribe' in stages or 'extract_audio' in stages:
                        if selected_audio is None:
                            self.transition(job_id, JobStatus.EXTRACTING_AUDIO)
                            audio = work / checkpoints.run("extract", lambda: extract_audio(source, work, check).name,
                                files=("audio.wav",))
                        else:
                            audio = selected_audio
                        if plan['template'] == 'extract_audio':
                            output = repo.job_dir(job_id) / 'output'
                            shutil.copyfile(audio, output / 'audio.wav')
                            self.transition(job_id, JobStatus.COMPLETED, metadata={
                                'duration': metadata['duration'], 'result_files': ['audio.wav'],
                                'output_bytes': (output / 'audio.wav').stat().st_size})
                            return
                        self.transition(job_id, JobStatus.PREPROCESSING_AUDIO)
                        vocalizations = []
                        protected_audio = []
                        filter_enabled = os.getenv("VOCALIZATION_FILTER_ENABLED", "false").lower()
                        if filter_enabled not in {"true", "false"}:
                            raise ValueError("VOCALIZATION_FILTER_ENABLED must be true or false")
                        if filter_enabled == "true" and record.options.audio_filter != "off":
                            analysis = checkpoints.run("vocalizations", lambda: self.paid_call(job_id, check, lambda: self.provider.detect_vocalizations(
                                audio, record.options.source_language, check, strength=record.options.audio_filter))
                            )
                            vocalizations, protected_audio = analysis["removals"], analysis["protected"]
                            write_json_atomic(work / "vocalization-analysis.json", analysis)
                        def prepare_audio():
                            processed, timeline = preprocess_audio(audio, work, check, audio_filter=record.options.audio_filter,
                                vad_mode=record.options.vad_mode,
                                vocalizations=vocalizations, protected_audio=protected_audio)
                            return {"audio": processed.name, "spans": [span.to_dict() for span in timeline]}
                        prepared = checkpoints.run("preprocess", prepare_audio,
                            files=("processed-audio.wav", "timeline-map.json"))
                        audio = work / prepared["audio"]
                        spans = [TimelineSpan.from_dict(span) for span in prepared["spans"]]
                        self.transition(job_id, JobStatus.PREPROCESSING_AUDIO, metadata={
                            "vocalization_filter_enabled": filter_enabled == "true" and record.options.audio_filter != "off",
                            "vocalization_removal_count": len(vocalizations)})
                        self.transition(job_id, JobStatus.TRANSCRIBING)
                        def transcription_progress(value):
                            with wait_for_job_lock(repo, job_id, check=check):
                                current = repo.read(job_id)
                                current.metadata["transcription_progress"] = value
                                current.metadata["transcription_blocks"] = value.get("content_blocks", [])
                                current.metadata["stage_progress"] = value["completed"] / value["total"] if value["total"] else 1
                                current.status_message = "진행 중 요청 회수 중" if value["draining"] else "음성 전사 중"
                                repo.save(current)
                        try:
                            segments = [TranscriptSegment.from_dict(item) for item in checkpoints.run("transcribe-packed-60-v2", lambda: self.paid_call(job_id, check, lambda: [
                                s.to_dict() for s in self.provider.transcribe(audio, record.options.source_language, check,
                                    spans=spans, work=work, progress=transcription_progress)]))]
                        except PartialTranscriptionError as exc:
                            partial = restore_segments(exc.segments, spans, work / "partial-cross-boundary.json")
                            prefix = restore_segments(exc.prefix, spans, work / "partial-prefix-cross-boundary.json")
                            write_json_atomic(work / "partial-transcript.json", {"incomplete": True,
                                "failed_segments": [index + 1 for index in exc.failed],
                                "segments": [s.to_dict() for s in filter_transcript_segments(partial, record.options.audio_filter)]})
                            cues = segment_subtitles(filter_transcript_segments(prefix, record.options.audio_filter),
                                line_width=24 if record.options.source_language in {"auto", "ko", "ja", "zh"} else 42)
                            (work / "partial-original.srt").write_text(segments_to_srt(cues), encoding="utf-8")
                            raise
                        segments = restore_segments(segments, spans, work / "cross-boundary.json")
                        self.transition(job_id, JobStatus.FILTERING_TRANSCRIPT)
                        segments = filter_transcript_segments(segments, record.options.audio_filter)
                        save_completed_transcript(work, completed_identity, [s.to_dict() for s in segments],
                            getattr(self.provider, "transcription_identity", getattr(self.provider, "transcription_model", None)), checkpoints.before_write)
                        write_json_atomic(work / "transcript.json", [s.to_dict() for s in segments])
                    else:
                        segments = selected
                        write_json_atomic(work / "transcript.json", [s.to_dict() for s in segments])
                    if languages:
                        self.transition(job_id, JobStatus.TRANSLATING)
                    subtitle_sets = {"original": selected if selected is not None else segment_subtitles(segments,
                        line_width=24 if record.options.source_language in {"auto", "ko", "ja", "zh"} else 42)}
                    for index, language in enumerate(languages):
                        check()
                        stem = "translated" if index == 0 else f"translated.{language}"
                        def translation_progress(value):
                            with wait_for_job_lock(repo, job_id, check=check):
                                current = repo.read(job_id)
                                current.metadata["translation_progress"] = {**value, "language": language}
                                current.metadata.setdefault("translation_blocks", {})[language] = value.get("content_blocks", [])
                                current.metadata["stage_progress"] = value["completed"] / value["total"] if value["total"] else 1
                                current.status_message = "진행 중 번역 요청 회수 중" if value["draining"] else "자막 번역 중"
                                repo.save(current)
                        try:
                            translated = [TranscriptSegment.from_dict(item) for item in checkpoints.run("translate-packed-40-v2-" + language,
                                lambda: self.paid_call(job_id, check, lambda: [s.to_dict() for s in self.provider.translate(segments, language, check,
                                    work=work, progress=translation_progress,
                                    video_description=record.options.video_description)]))]
                        except PartialTranslationError as exc:
                            write_json_atomic(work / f"partial-{stem}.json", {"incomplete": True,
                                "failed_batches": [i + 1 for i in exc.failed],
                                "segments": [s.to_dict() for s in exc.segments]})
                            cues = segment_subtitles(exc.prefix, line_width=24 if language.split("-")[0] in {"ko", "ja", "zh"} else 42)
                            (work / f"partial-{stem}.srt").write_text(segments_to_srt(cues), encoding="utf-8")
                            raise
                        write_json_atomic(work / f"{stem}.json", [s.to_dict() for s in translated])
                        subtitle_sets[stem] = segment_subtitles(translated,
                            line_width=24 if language.split("-")[0] in {"ko", "ja", "zh"} else 42)
                    has_blocks = any(BLOCKED_TEXT in cue.text for cues in subtitle_sets.values() for cue in cues)
                    if (record.options.review_subtitles or has_blocks) and 'encode' in stages:
                        needs_review = True
                        with wait_for_job_lock(repo, "0" * 32, check=check):
                            write_draft(repo, record, {name: [cue.to_dict() for cue in cues]
                                for name, cues in subtitle_sets.items()}, metadata["duration"], 1,
                                capacity_check=lambda size: assert_capacity(repo.storage_root,
                                    int(os.getenv("VIDEO_SERVICE_QUOTA_BYTES", str(300 * 1024**3))),
                                    int(os.getenv("MIN_FREE_SPACE_BYTES", str(50 * 1024**3))), additional=size))
                self.transition(job_id, JobStatus.GENERATING_SUBTITLE)
                output = repo.job_dir(job_id) / "output"
                output.mkdir(exist_ok=True)
                result_files = []
                for index, language in enumerate(languages):
                    check()
                    stem = "translated" if index == 0 else f"translated.{language}"
                    cues = subtitle_sets[stem]
                    if plan['template'] == 'encode':
                        validate_input_cues([s.to_dict() for s in cues], metadata['duration'])
                    else:
                        validate_cues(cues, metadata["duration"])
                    srt = segments_to_srt(cues)
                    (output / f"{stem}.srt").write_text(srt, encoding="utf-8")
                    sami_cues = segment_subtitles(cues) if selected is not None else cues
                    (output / f"{stem}.smi").write_text(segments_to_sami(sami_cues, language), encoding="utf-8")
                    (work / f"{stem}.srt").write_text(srt, encoding="utf-8")
                    result_files.extend([f"{stem}.srt", f"{stem}.smi"])
                if 'original' in subtitle_sets:
                    original_cues = subtitle_sets["original"]
                    if selected is not None:
                        validate_input_cues([s.to_dict() for s in original_cues], metadata['duration'])
                    else:
                        validate_cues(original_cues, metadata["duration"])
                    (output / "original.srt").write_text(segments_to_srt(original_cues), encoding="utf-8")
                    result_files.append('original.srt')
                if needs_review:
                    self.transition(job_id, JobStatus.AWAITING_REVIEW,
                        message="차단 구간이 포함되어 인코딩 전 검토가 필요합니다." if has_blocks else None,
                        metadata={"awaiting_review_at": utc_now_iso(), "content_block_review": has_blocks,
                                  "result_files": result_files})
                    return
                if 'encode' not in stages:
                    self.transition(job_id, JobStatus.COMPLETED, metadata={
                        'duration': metadata['duration'], 'result_files': result_files,
                        'output_bytes': sum((output / name).stat().st_size for name in result_files)})
                    return
                self.transition(job_id, JobStatus.ENCODING, message="인코딩 슬롯 대기 중")
                target = (output / "final.mp4").resolve()
                with gpu_slot(check), encoding_slot(repo, int(os.getenv("MAX_ENCODING_JOBS", "1")), check):
                    if encoder is None:
                        encoder = select_encoder(work, check, video_codec=record.options.video_codec)
                    software = encoder in {"libx265", "libx264"}
                    self.transition(job_id, JobStatus.ENCODING, message="영상 인코딩 중")
                    progress_path = work / "encode.log"
                    progress_duration = metadata["duration"]
                    def encode_output():
                        run_process(encoding_args(source, target, videos[0], record.options.quality_profile.value, software,
                            record.options.video_codec, record.options.subtitle_mode, record.options.target_language,
                            record.options.resolution, record.options.additional_languages),
                            cwd=work, log_name="encode.log", check=check)
                        return 'final.mp4'
                    checkpoints.run('encode-output-v1', encode_output, files=('../output/final.mp4',))
                    progress_path = None
                self.transition(job_id, JobStatus.VALIDATING, message="출력 영상 정보 확인 중")
                final = probe(target, work, check)
                validate_output(metadata, final, target.stat().st_size, record.options.video_codec,
                    record.options.subtitle_mode, record.options.resolution,
                    subtitle_count=len(languages))
                self.transition(job_id, JobStatus.VALIDATING, message="출력 영상·오디오 전체 무결성 검사 중")
                progress_path = work / 'validate-decode.log'
                progress_duration = final['duration']
                validate_decodable(target, work, check)
                progress_path = None
                size = target.stat().st_size
                result_files.insert(0, 'final.mp4')
                self.transition(job_id, JobStatus.COMPLETED, metadata={"output_bytes": size,
                    "duration": final["duration"], "encoder": encoder,
                    "result_files": result_files})
            except (Exception, KeyboardInterrupt) as exc:
                cancelled = isinstance(exc, (Cancelled, KeyboardInterrupt))
                with wait_for_job_lock(repo, job_id):
                    current = repo.read(job_id)
                    cancelled = cancelled or current.metadata.get("cancel_requested", False)
                    failure = None if cancelled else block_details(exc)
                    if failure:
                        failure["stage"] = current.status.value
                    repo.update_status(job_id, JobStatus.CANCELLED if cancelled else JobStatus.FAILED,
                        error=None if cancelled else f"{failure['provider']} 콘텐츠 정책에 의해 차단되었습니다. 자동 재시도를 중단했습니다." if failure else str(exc),
                        metadata={"stage_progress": None, "failure": failure,
                            "interrupted": isinstance(exc, WorkerStopping) or self.stop.is_set(),
                            "failed_stage": current.status.value,
                            "wait_reason": None, "wait_started_at": None,
                            "cleanup_pending": False, "cleanup_error": None})
                if isinstance(exc, KeyboardInterrupt):
                    raise

    def paid_call(self, job_id, check, operation):
        with resource_slot('llm', check):
            with wait_for_job_lock(self.repository, job_id, check=check):
                record = self.repository.read(job_id)
                record.metadata['paid_operation_in_flight'] = True
                self.repository.save(record)
            from video_service.execution_authorization import node_scope
            with node_scope(record.status.value,record.metadata.get('execution_authorization',{}).get('execution_id','legacy')):
                result = operation()
            # Cleared at the next stage transition, after checkpoint publication.
            return result

    def collect(self, *, expire=True):
        if self.stop.is_set():
            return
        result_ttl = float(os.getenv("RESULT_TTL_HOURS", "24")) * 3600
        history_ttl = float(os.getenv("HISTORY_TTL_DAYS", "90")) * 86400
        upload_ttl = float(os.getenv("UPLOAD_TTL_HOURS", "6")) * 3600
        review_ttl = float(os.getenv("REVIEW_TTL_HOURS", "24")) * 3600
        if any(not math.isfinite(value) or value < 0 for value in (result_ttl, history_ttl, upload_ttl, review_ttl)):
            raise ValueError("Retention periods must be finite and nonnegative")
        history_ttl = max(history_ttl, result_ttl)
        if expire:
            collect_orphans(self.repository, grace_seconds=float(os.getenv("ORPHAN_GRACE_HOURS", "2")) * 3600)
        now = datetime.now(timezone.utc)
        for record in self.repository.list():
            if self.stop.is_set():
                return
            try:
                with job_lock(self.repository, record.job_id, "execution"), job_lock(self.repository, record.job_id):
                    record = self.repository.read(record.job_id)
                    if (record.status == JobStatus.FAILED and record.metadata.get('interrupted')
                            and not record.metadata.get('recovery_required')):
                        from .recovery import recover_interrupted
                        if recover_interrupted(self.repository, record):
                            continue
                    if not expire and record.status in (*TERMINAL_STATUSES, JobStatus.UPLOADING, JobStatus.AWAITING_REVIEW):
                        continue
                    age = (now - datetime.fromisoformat(record.completed_at or record.updated_at)).total_seconds()
                    if record.status in TERMINAL_STATUSES:
                        if age > history_ttl:
                            self.repository.delete_job_dir(record.job_id)
                            continue
                        expired = age > result_ttl or bool(record.metadata.get("results_expired_at"))
                        if expired:
                            self.cleanup(record.job_id)
                        changed = False
                        if record.metadata.get("cleanup_pending"):
                            record.metadata.update(cleanup_pending=False, cleanup_error=None)
                            changed = True
                        if expired and not record.metadata.get("results_expired_at"):
                            record.metadata["results_expired_at"] = now.isoformat()
                            changed = True
                        if changed:
                            self.repository.save(record)
                    elif record.status == JobStatus.AWAITING_REVIEW:
                        review_age = (now - datetime.fromisoformat(record.metadata.get("awaiting_review_at", record.updated_at))).total_seconds()
                        if review_age > review_ttl:
                            self.cleanup(record.job_id)
                            self.repository.update_status(record.job_id, JobStatus.CANCELLED,
                                message="자막 검토 보관 기간이 만료되었습니다.",
                                metadata={"review_expired_at": now.isoformat()})
                    elif record.status == JobStatus.UPLOADING:
                        if age > upload_ttl:
                            self.cleanup(record.job_id)
                            self.repository.update_status(record.job_id, JobStatus.CANCELLED,
                                message="업로드 보관 기간이 만료되었습니다.",
                                metadata={"upload_expired_at": now.isoformat()})
                    elif record.status not in {JobStatus.QUEUED, JobStatus.READY}:
                        from .recovery import recover_interrupted
                        if recover_interrupted(self.repository, record):
                            continue
                        self.repository.update_status(record.job_id, JobStatus.FAILED, error="Worker interrupted; retry to resume",
                            metadata={"interrupted": True, "failed_stage": record.status.value})
            except (JobBusyError, JobNotFoundError):
                continue
            except OSError:
                logging.exception("Collection deferred for job %s", record.job_id)

    def tick(self):
        try:
            with job_lock(self.repository, "f" * 32, "execution"):
                if int(os.getenv('MAX_CONCURRENT_JOBS', '1')) > 1:
                    self._tick_parallel()
                else:
                    self._tick_serial()
        except JobBusyError:
            return

    def _tick_serial(self):
        if self.stop.is_set():
            return
        from .faceswap.runner import refresh_capabilities
        with job_resources(self.repository, None), gpu_slot(self.check_stopping, keep_preview=True):
            refresh_capabilities(self.repository, self.stop)
        self.collect(expire=False)
        jobs = self.repository.find_by_statuses([JobStatus.QUEUED])
        for job in QueueControl(self.repository.storage_root).ordered(jobs):
            if self.stop.is_set():
                return
            try:
                self.process(job.job_id)
            except (JobBusyError, JobNotFoundError):
                continue

    def _tick_parallel(self):
        limit = int(os.getenv('MAX_CONCURRENT_JOBS', '1'))
        if not 1 <= limit <= 8:
            raise ValueError('MAX_CONCURRENT_JOBS must be between 1 and 8')
        if self.stop.is_set():
            return
        for identity, future in list(self._active.items()):
            if future.done():
                del self._active[identity]
                try:
                    future.result()
                except (JobBusyError, JobNotFoundError):
                    pass
                except Exception:
                    logging.exception('Concurrent worker failed for %s', identity)
        if not self._active:
            from .faceswap.runner import refresh_capabilities
            with job_resources(self.repository, None), gpu_slot(self.check_stopping, keep_preview=True):
                refresh_capabilities(self.repository, self.stop)
        self.collect(expire=False)
        if self._pool is None:
            self._pool = ThreadPoolExecutor(max_workers=limit, thread_name_prefix='media-job')
        jobs = QueueControl(self.repository.storage_root).ordered(
            self.repository.find_by_statuses([JobStatus.QUEUED]))
        def admission_resource(record):
            if record.metadata.get('faceswap_operation'):
                return 'gpu'
            if record.status == JobStatus.ENCODING:
                return 'gpu'
            if record.status in {JobStatus.VALIDATING, JobStatus.GENERATING_SUBTITLE}:
                return 'io'
            workflow = record.metadata.get('workflow', {})
            if workflow.get('template') == 'encode':
                return 'gpu'
            if workflow.get('template') == 'extract_audio':
                return 'io'
            return 'llm'
        occupied = {resource: 0 for resource in LIMITS}
        for identity in self._active:
            occupied[admission_resource(self.repository.read(identity))] += 1
        for job in jobs:
            if len(self._active) >= limit or self.stop.is_set():
                break
            if job.job_id in self._active:
                continue
            resource = admission_resource(job)
            name, default = LIMITS[resource]
            # Do not fill every execution slot with jobs waiting for the same
            # resource; continue scanning for independent work further in the queue.
            if occupied[resource] >= int(os.getenv(name, str(default))):
                continue
            # Each job owns a provider instance. ContextVars and resource leases are
            # scoped to the executing thread, not shared mutable provider settings.
            child = Worker(self.repository, self.provider, self.stop, self.provider_factory)
            self._active[job.job_id] = self._pool.submit(child.process, job.job_id)
            occupied[resource] += 1

    def close(self):
        self.stop.set()
        if self._pool is not None:
            self._pool.shutdown(wait=True, cancel_futures=True)
            self._pool = None

    def run(self, poll_interval=5):
        wakeup = self.repository.storage_root / '.faceswap-wakeup'
        def generation():
            try:
                return wakeup.stat().st_mtime_ns
            except FileNotFoundError:
                return 0
        try:
            while not self.stop.is_set():
                try:
                    before = generation()
                    self.tick()
                    deadline = time.monotonic() + (min(.5, poll_interval) if self._active else poll_interval)
                    while generation() == before and time.monotonic() < deadline:
                        if self.stop.wait(min(.1, max(0, deadline - time.monotonic()))):
                            break
                except KeyboardInterrupt:
                    self.stop.set()
                except Exception:
                    logging.exception("Worker iteration failed")
                    self.stop.wait(5)
        finally:
            self.close()
            from .faceswap.warm import release
            release()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--collect-only", action="store_true", help="Delete expired artifacts once; do not process jobs")
    args = parser.parse_args()
    load_environment()
    logging.basicConfig(level=logging.INFO)
    repo = FilesystemJobRepository(Path(os.getenv("VIDEO_STORAGE_ROOT", "data/video-jobs")).resolve())
    worker = Worker(repo, None, provider_factory=None if args.collect_only else
                    lambda owner: GeminiProvider(LLMSettingsStore(repo.storage_root).resolve(owner)))
    with shutdown_signals(worker.stop):
        if args.collect_only:
            worker.collect()
        else:
            worker.run(float(os.getenv("WORKER_POLL_INTERVAL_SECONDS", "5")))


if __name__ == "__main__":
    main()
