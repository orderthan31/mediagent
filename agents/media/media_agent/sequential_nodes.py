"""Real per-node adapters over existing media/provider/clock/integrity helpers."""
import hashlib
import json
import os
import shutil
from pathlib import Path
from video_service.storage import write_json_atomic, read_json
from video_service.timeline import TimelineSpan
from video_service.transcript import TranscriptSegment, filter_transcript_segments
from video_service.subtitles import segment_subtitles, segments_to_srt
from .media import probe, extract_audio, preprocess_audio, encoding_args
from .process import run_process
from .providers import GeminiProvider
from .packed_timeline import restore_segments
from .completed_transcript import load_completed_transcript, save_completed_transcript
from .transcription_queue import PartialTranscriptionError, PartialTranslationError
from .content_block import BLOCKED_TEXT
from .validation import validate_cues, validate_output, validate_decodable


class MediaNodeExecutor:
    def __init__(self, preferences, options, *, provider=None, paid_allowed=False):
        self.provider=provider if provider is not None else GeminiProvider(preferences)
        self.options=options;self.paid_allowed=paid_allowed;self.source=None;self.audio_filter='off';self.language=options.get('source_language','auto');self.encode_options=None

    def _paid(self, role, operation):
        if not self.paid_allowed:raise PermissionError('명시적인 유료 실행 허용이 없습니다.')
        if hasattr(self.provider,'validate_for_stages'):self.provider.validate_for_stages([role])
        return operation()

    def __call__(self, step, inputs, work, check):
        kind=step['type'];options=step['options'];check()
        if kind=='analyze':
            data=probe(inputs['video'],work,check);data.get('format',{}).pop('filename',None)
            path=work/'metadata.json';write_json_atomic(path,data);return {'metadata':path}
        if kind=='extract_audio':
            self.source=inputs['video'];return {'audio':extract_audio(self.source,work,check)}
        if kind=='preprocess_audio':
            self.audio_filter=options['audio_filter']
            if os.getenv('VOCALIZATION_FILTER_ENABLED','false').lower()!='false' and self.audio_filter!='off':
                raise ValueError('유료 발성분석이 켜진 환경의 새 순차 전처리는 아직 지원하지 않습니다.')
            if options['vad_mode']!='off':raise ValueError('새 순차 GPU VAD 어댑터는 지원하지 않습니다.')
            audio,spans=preprocess_audio(inputs['audio'],work,check,audio_filter=self.audio_filter,vad_mode=options['vad_mode'])
            return {'audio':audio,'timeline':work/'timeline-map.json'}
        if kind=='transcribe':
            spans=[TimelineSpan.from_dict(x) for x in read_json(inputs['timeline'])]
            def sha(path):
                with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
            identity={'version':1,'audio_sha256':sha(inputs['audio']),'timeline_sha256':sha(inputs['timeline']),
                      'source_language':self.options.get('source_language','auto'),'audio_filter':self.audio_filter}
            completed=load_completed_transcript(work,identity)
            if completed is None:
                try:
                    packed=self._paid('transcribe',lambda:list(self.provider.transcribe(inputs['audio'],self.options.get('source_language','auto'),check,spans=spans,work=work)))
                except PartialTranscriptionError as exc:
                    partial=filter_transcript_segments(restore_segments(exc.segments,spans,work/'partial-cross-boundary.json'),self.audio_filter)
                    prefix=filter_transcript_segments(restore_segments(exc.prefix,spans,work/'partial-prefix-cross-boundary.json'),self.audio_filter)
                    write_json_atomic(work/'partial-transcript.json',{'incomplete':True,'failed_segments':exc.failed,'segments':[s.to_dict() for s in partial]})
                    (work/'partial-original.srt').write_text(segments_to_srt(segment_subtitles(prefix)),encoding='utf-8');raise
                segments=filter_transcript_segments(restore_segments(packed,spans,work/'cross-boundary.json'),self.audio_filter)
                completed=[s.to_dict() for s in segments]
                save_completed_transcript(work,identity,completed,getattr(self.provider,'transcription_identity','unknown'))
            path=work/'transcript.json';write_json_atomic(path,completed);return {'transcript':path}
        if kind=='translate':
            segments=[TranscriptSegment.from_dict(x) for x in read_json(inputs['transcript'])]
            language=self.options.get('target_language','ko')
            try:
                translated=self._paid('translate',lambda:list(self.provider.translate(segments,language,check,work=work,video_description=self.options.get('video_description',''))))
            except PartialTranslationError as exc:
                write_json_atomic(work/'partial-translated.json',{'incomplete':True,'failed_batches':exc.failed,'segments':[s.to_dict() for s in exc.segments]})
                (work/'partial-translated.srt').write_text(segments_to_srt(segment_subtitles(exc.prefix)),encoding='utf-8');raise
            self.language=language;path=work/'translated.json';write_json_atomic(path,[s.to_dict() for s in translated]);return {'transcript':path}
        if kind=='generate_subtitle':
            segments=[TranscriptSegment.from_dict(x) for x in read_json(inputs['transcript'])]
            cues=segment_subtitles(segments,line_width=24 if self.language.split('-')[0] in {'auto','ko','ja','zh'} else 42)
            metadata=probe(self.source,work,check);validate_cues(cues,metadata['duration'])
            blocked=any(BLOCKED_TEXT in cue.text for cue in cues)
            path=work/('partial-blocked.srt' if blocked else 'subtitles.srt');path.write_text(segments_to_srt(cues),encoding='utf-8')
            if blocked:raise ValueError('차단된 자막은 검수 없이 인코딩하지 않습니다. 새 검수 실행은 미지원입니다.')
            return {'subtitles':path}
        if kind=='encode':
            self.source=inputs['video'];self.encode_options=options
            metadata=probe(self.source,work,check);stream=next(s for s in metadata['streams'] if s['codec_type']=='video')
            if options['subtitle_mode']!='none':shutil.copyfile(inputs['subtitles'],work/'translated.srt')
            target=work/'final.mp4'
            run_process(encoding_args(self.source,target,stream,options['quality_profile'],True,options['video_codec'],options['subtitle_mode'],self.options.get('target_language','ko'),options['resolution']),cwd=work,log_name='encode.log',check=check)
            return {'video':target}
        if kind=='validate_video':
            original=probe(self.source,work,check);final=probe(inputs['video'],work,check);o=self.encode_options
            validate_output(original,final,inputs['video'].stat().st_size,o['video_codec'],o['subtitle_mode'],o['resolution']);validate_decodable(inputs['video'],work,check)
            path=work/'validation.json';write_json_atomic(path,{'valid':True,'duration':final['duration'],'bytes':inputs['video'].stat().st_size,'video_codec':o['video_codec']});return {'report':path}
        raise ValueError('지원하지 않는 순차 노드 어댑터입니다.')


def run_media_ticket(root, owner, identity, *, allow_paid=False):
    """Explicit operator invocation only; no watcher/legacy queue or API auto-start."""
    from video_service.workflow_tickets import TicketStore
    from video_service.llm_settings import LLMSettingsStore
    from video_service.repository import FilesystemJobRepository
    from video_service.assets import VideoAssetRepository
    store=TicketStore(root,owner);record=store.get(identity)
    if record['sequence']['paid_roles'] and not allow_paid:raise PermissionError('운영자의 별도 유료 실행 허용이 필요합니다.')
    assets=VideoAssetRepository(FilesystemJobRepository(root));asset=assets.read(record['asset']['asset_id'],owner_id=owner)
    preferences=LLMSettingsStore(root).resolve(owner)
    return store.run(identity,preferences,assets.source_path(asset),lambda bound,options:MediaNodeExecutor(bound,options,paid_allowed=allow_paid and record['confirmation']['paid_confirmed']))
