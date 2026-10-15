"""Persistent, sequential frame-range queue with one chunk's PNGs on disk at a time."""
from fractions import Fraction
import hashlib
import math
import os
from pathlib import Path
import re
import time
from uuid import uuid4

from video_service.faceswap import digest
from video_service.locking import encoding_slot
from video_service.models import JobStatus
from video_service.storage import read_json, write_json_atomic, remove_path_inside
from ..media import executable, probe, encoding_args, select_encoder
from ..progress import encoding_progress
from ..validation import validate_decodable
from .process import run

PIPELINE_VERSION = 1


def plan_chunks(frame_count, fps, seconds=600):
    if (type(frame_count) is not int or frame_count <= 0 or not math.isfinite(fps)
            or fps <= 0 or not 1 <= seconds <= 600):
        raise ValueError('Invalid face-swap chunk timeline')
    step = max(1, math.floor(fps * seconds))
    return [{'index': i, 'start': start, 'end': min(start + step, frame_count),
             'fps': fps, 'start_seconds': start / fps,
             'duration': (min(start + step, frame_count) - start) / fps}
            for i, start in enumerate(range(0, frame_count, step))]


def checksum(path, check):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            check()
            value.update(block)
    return value.hexdigest()


def reusable(entry, path, check):
    return (entry.get('status') == 'completed' and path.is_file()
            and path.stat().st_size == entry.get('size') and checksum(path, check) == entry.get('sha256'))


def assert_cfr(log):
    text = log.read_text(encoding='utf-8', errors='replace')
    match = re.search(r'VFR:([\d.]+)\s+\(', text)
    if not match:
        raise ValueError('영상 타임스탬프를 검사하지 못했습니다.')
    if float(match[1]) > 0:
        durations = re.search(r'min:\s*(\d+)\s+max:\s*(\d+)', text)
        # Allow the one-tick quantization of fractional CFR in coarse time bases.
        if not durations or int(durations[2]) - int(durations[1]) > 1:
            raise ValueError('가변 프레임 영상입니다. CFR 영상으로 변환 후 합성하세요. 청크 시간축을 임의로 변경하지 않습니다.')


def validate_chunk(metadata, chunk):
    video = next((s for s in metadata['streams'] if s['codec_type'] == 'video'), None)
    if not video or int(video.get('nb_frames', 0)) != chunk['end'] - chunk['start']:
        raise ValueError('합성 청크의 프레임 수가 일치하지 않습니다.')
    if abs(float(Fraction(video['avg_frame_rate'])) - chunk['fps']) > .001:
        raise ValueError('합성 청크의 프레임 속도가 일치하지 않습니다.')
    if abs(metadata['duration'] - chunk['duration']) > max(.05, 1 / chunk['fps']):
        raise ValueError('합성 청크의 시간축이 일치하지 않습니다.')


def render_chunks(worker, record, payload, work, check, invoke):
    repo = worker.repository
    original = probe(Path(payload['target']), work, check)
    source_video = next(s for s in original['streams'] if s['codec_type'] == 'video')
    timeout = int(os.getenv('FACEFUSION_TIMEOUT_SECONDS', '86400'))
    info_work = work / 'inspect'
    info_work.mkdir()
    invoke({**payload, 'operation': 'inspect_video', 'output': str(info_work / 'output')}, info_work, check, 300)
    info = read_json(info_work / 'output/result.json')
    frame_count, fps = info['frame_count'], info['fps']
    chunks = plan_chunks(frame_count, fps, record.metadata.get('faceswap_chunk_seconds', 600))
    timeline_duration = frame_count / fps
    if abs(float(source_video.get('duration', timeline_duration)) - timeline_duration) > max(.1, 1 / fps):
        raise ValueError('영상 프레임 수와 원본 시간축이 일치하지 않습니다.')
    key = digest({'pipeline': PIPELINE_VERSION, 'input': record.metadata['faceswap_key'], 'chunks': chunks})
    cache = repo.job_dir(record.job_id) / 'work' / ('faceswap-chunks-' + key)
    cache.mkdir(exist_ok=True)
    # A previous Worker crash may have left extraction frames. The execution lock
    # and engine process-tree lifetime guarantee that these attempts are inactive.
    for old_attempt in cache.glob('attempt-*'):
        remove_path_inside(cache, old_attempt / 'temp')
    manifest_path = cache / 'queue.json'
    state = read_json(manifest_path) if manifest_path.exists() else {
        'version': PIPELINE_VERSION, 'key': key, 'chunks': [{**c, 'status': 'pending'} for c in chunks]}
    if not state.get('timeline_checked'):
        worker.transition(record.job_id, JobStatus.ANALYZING, message='청크 분할 전 영상 시간축 검사')
        run([executable('ffmpeg'), '-nostdin', '-v', 'info', '-i', payload['target'],
             '-map', '0:v:0', '-an', '-vf', 'vfrdet', '-f', 'null', '-'], cwd=work,
            env=os.environ.copy(), log=work / 'timeline.log', check=check, timeout=timeout)
        assert_cfr(work / 'timeline.log')
        state['timeline_checked'] = True
        write_json_atomic(manifest_path, state)
    for entry in state['chunks']:
        check()
        chunk = chunks[entry['index']]
        result_path = cache / f"chunk-{chunk['index']:05d}.mp4"
        if reusable(entry, result_path, check):
            continue
        attempt = cache / ('attempt-' + uuid4().hex)
        attempt.mkdir()
        entry['status'] = 'running'
        write_json_atomic(manifest_path, state)
        last_update = 0
        def monitor():
            nonlocal last_update
            check()
            if time.monotonic() - last_update < 2:
                return
            fraction = 0
            log = attempt / 'engine.log'
            if log.is_file():
                with log.open('rb') as stream:
                    stream.seek(max(0, log.stat().st_size - 8192))
                    matches = re.findall(rb'processing:\s*(\d+)%', stream.read())
                if matches:
                    fraction = min(.99, int(matches[-1]) / 100)
            worker.transition(record.job_id, JobStatus.FACE_SWAPPING,
                message=f"얼굴 합성 청크 {chunk['index'] + 1}/{len(chunks)} · 완료 {chunk['index']}개",
                metadata={'stage_progress': (chunk['start'] + fraction * (chunk['end'] - chunk['start'])) / frame_count,
                          'faceswap_chunks': {'total': len(chunks), 'completed': chunk['index'],
                                              'current': chunk['index'] + 1, 'seconds': record.metadata.get('faceswap_chunk_seconds', 600)}})
            last_update = time.monotonic()
        try:
            monitor()
            invoke({**payload, 'chunk': chunk, 'output': str(attempt / 'output')}, attempt, monitor, timeout)
            candidate = attempt / 'output/final.mp4'
            validate_chunk(probe(candidate, attempt, check), chunk)
            validate_decodable(candidate, attempt, check)
            sha256 = checksum(candidate, check)
            candidate.replace(result_path)
            entry.update(status='completed', sha256=sha256, size=result_path.stat().st_size)
            write_json_atomic(manifest_path, state)
        except BaseException:
            entry['status'] = 'failed'
            write_json_atomic(manifest_path, state)
            raise
        finally:
            # Only disposable extraction frames inside this job's attempt are removed.
            remove_path_inside(cache, attempt / 'temp')
    worker.transition(record.job_id, JobStatus.ENCODING, message='청크 연결 및 원본 오디오 시간축 정리',
        metadata={'faceswap_chunks': {'total': len(chunks), 'completed': len(chunks), 'current': None,
                                      'seconds': record.metadata.get('faceswap_chunk_seconds', 600)}})
    # Generated relative paths only: no user filenames in ffconcat syntax.
    listing = cache / 'chunks.ffconcat'
    listing.write_text('ffconcat version 1.0\n' + ''.join(
        f"file chunk-{c['index']:05d}.mp4\nduration {c['duration']:.12f}\n" for c in chunks), encoding='utf-8')
    joined = work / 'joined.mkv'
    audio = next((s for s in original['streams'] if s['codec_type'] == 'audio'), None)
    args = [executable('ffmpeg'), '-nostdin', '-y', '-fflags', '+genpts', '-f', 'concat', '-safe', '1',
            '-i', str(listing), '-i', payload['target'], '-map', '0:v:0', '-map', '1:a:0?', '-c:v', 'copy']
    if audio:
        offset = float(audio.get('start_time', 0)) - float(source_video.get('start_time', 0))
        args += ['-af', f'asetpts=PTS-STARTPTS+({offset:.9f})/TB,aresample=async=1:first_pts=0', '-c:a', 'flac']
    args += ['-t', str(timeline_duration), str(joined)]
    run(args, cwd=work, env=os.environ.copy(), log=work / 'join.log', check=check, timeout=timeout)
    output = Path(payload['output'])
    output.mkdir(exist_ok=True)
    target = output / 'final.mp4'
    with encoding_slot(repo, int(os.getenv('MAX_ENCODING_JOBS', '1')), check):
        encoder = select_encoder(work, check, video_codec=record.options.video_codec)
        command = encoding_args(joined, target, source_video, record.options.quality_profile.value,
                                encoder.startswith('lib'), record.options.video_codec, subtitle_mode='none')
        # Reuse burn-in encoder settings, but rebuild one continuous CFR presentation clock.
        command[-1:-1] = ['-vf', f'setpts=N/({fps:.12f}*TB)', '-fps_mode', 'cfr', '-r', str(fps)]
        last_update = 0
        def encoding_check():
            nonlocal last_update
            check()
            if time.monotonic() - last_update > 2:
                worker.transition(record.job_id, JobStatus.ENCODING, message='연결 영상 최종 인코딩 및 탐색 정보 정리',
                    metadata={'stage_progress': encoding_progress(work / 'encode.log', timeline_duration)})
                last_update = time.monotonic()
        run(command, cwd=work, env=os.environ.copy(), log=work / 'encode.log', check=encoding_check, timeout=timeout)
    write_json_atomic(output / 'result.json', {'file': 'final.mp4', 'chunks': len(chunks),
                                              'frame_count': frame_count, 'fps': fps, 'encoder': encoder})
    return original
