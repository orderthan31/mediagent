import hashlib
import os
from pathlib import Path
import re
import time
from uuid import uuid4

from video_service.models import JobStatus, utc_now_iso
from video_service.storage import write_json_atomic, read_json, remove_path_inside
from video_service.faceswap import digest
from .process import run


def environment():
    python = Path(os.environ.get('FACEFUSION_PYTHON', '/opt/facefusion-env/bin/python'))
    engine = Path(os.environ.get('FACEFUSION_PATH', '/opt/facefusion'))
    if not python.is_file() or not (engine / 'facefusion.py').is_file():
        raise ValueError('FaceFusion 전용 Python 및 엔진 경로를 설정하세요.')
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUNBUFFERED='1')
    env.pop('PYTHONPATH', None)
    env['PATH'] = os.pathsep.join([str(python.parent), str(python.parent / 'Library/bin'),
                                  str(python.parent / 'Scripts'), env.get('PATH', '')])
    # Avoid exposing service credentials to an external engine process.
    for key in list(env):
        if key.endswith(('API_KEY', 'API_TOKEN')):
            env.pop(key)
    return python, engine, env


def invoke(payload, work, check, timeout):
    python, engine, env = environment()
    env['FACEFUSION_PARENT_PID'] = str(os.getpid())
    request = work / 'request.json'
    write_json_atomic(request, payload)
    run([str(python), '-B', str(Path(__file__).with_name('bridge.py')), '--engine', str(engine),
         '--request', str(request)], cwd=engine, env=env, log=work / 'engine.log', check=check, timeout=timeout)


def refresh_capabilities(repo, stop, *, force=False):
    path = repo.storage_root / '.faceswap-capabilities.json'
    if path.exists() and not force and time.time() - path.stat().st_mtime < 30:
        return
    enabled = os.environ.get('FACEFUSION_ENABLED', 'false').lower() == 'true'
    # Successful probe is reused only within this worker process/config lifetime.
    engine_path = Path(os.getenv('FACEFUSION_PATH') or '/opt/facefusion')
    signature = [(str(p), p.stat().st_size, p.stat().st_mtime_ns)
                 for pattern in ('facefusion/**/*.py', '.assets/models/*') for p in sorted(engine_path.glob(pattern)) if p.is_file()]
    cache_key = (str(repo.storage_root), str(engine_path), os.getenv('FACEFUSION_PYTHON'), digest(signature))
    cache = getattr(refresh_capabilities, 'cache', {})
    if enabled and cache_key in cache:
        result = dict(cache[cache_key])
    elif enabled:
        work = repo.storage_root / '.faceswap-probe' / uuid4().hex
        work.mkdir(parents=True)
        def check():
            if stop.is_set():
                raise RuntimeError('Worker stopping')
        try:
            invoke({'operation': 'capabilities', 'output': str(work / 'output')}, work, check, 180)
            result = read_json(work / 'output/result.json')
            cache[cache_key] = result
            refresh_capabilities.cache = cache
        except Exception:
            result = {'ready': False, 'reason': 'FaceFusion 초기화 실패: Worker의 엔진 경로·모델·CUDA 로그를 확인하세요.', 'presets': []}
    else:
        result = {'ready': False, 'reason': '얼굴 합성 기능이 비활성화되어 있습니다.', 'presets': []}
    write_json_atomic(path, {**result, 'checked_at': utc_now_iso()})


def heartbeat_capabilities(repo):
    path = repo.storage_root / '.faceswap-capabilities.json'
    if os.environ.get('FACEFUSION_ENABLED', 'false').lower() == 'true' and path.exists():
        result = read_json(path)
        write_json_atomic(path, {**result, 'checked_at': utc_now_iso()})


def execute(worker, record, check):
    if os.environ.get('FACEFUSION_ENABLED', 'false').lower() != 'true':
        raise ValueError('이 Worker에서 얼굴 합성 기능이 비활성화되어 있습니다.')
    from ..media import probe
    from ..validation import validate_decodable
    repo = worker.repository
    root = repo.job_dir(record.job_id)
    snapshot = read_json(root / 'input/faceswap.json')
    if digest(snapshot) != record.metadata['faceswap_key']:
        raise ValueError('얼굴 합성 설정 무결성 검사 실패')
    source = root / 'input/source.jpg'
    if snapshot['source_sha256'] and hashlib.sha256(source.read_bytes()).hexdigest() != snapshot['source_sha256']:
        raise ValueError('Source 이미지 무결성 검사 실패')
    work = root / 'work' / ('faceswap-' + uuid4().hex)
    work.mkdir(parents=True)
    operation = record.metadata['faceswap_operation']
    output = work / 'output'
    payload = {**snapshot, 'operation': operation, 'source': str(source.resolve()),
               'target': str(repo.source_path(record).resolve()), 'output': str(output.resolve()),
               'preview_frame': record.metadata['preview_frame']}
    worker.transition(record.job_id, JobStatus.FACE_SWAPPING,
                      message='전체 영상 얼굴 합성' if operation == 'render' else '얼굴 분석 및 미리보기')
    last = 0
    def monitor():
        nonlocal last
        check()
        if time.monotonic() - last > 2:
            heartbeat_capabilities(repo)
            log = work / 'engine.log'
            if operation == 'render' and log.exists():
                with log.open('rb') as stream:
                    stream.seek(max(0, log.stat().st_size - 8192))
                    matches = re.findall(rb'processing:\s*(\d+)%', stream.read())
                if matches:
                    from video_service.locking import job_lock, JobBusyError
                    try:
                        with job_lock(repo, record.job_id):
                            current = repo.read(record.job_id)
                            current.metadata['stage_progress'] = min(.99, int(matches[-1]) / 100)
                            repo.save(current)
                    except JobBusyError:
                        pass
            last = time.monotonic()
    if operation == 'render':
        from .chunks import render_chunks
        for old in (root / 'work').glob('faceswap-*'):
            remove_path_inside(root, old / 'joined.mkv')
        try:
            original = render_chunks(worker, record, payload, work, check, invoke)
        finally:
            remove_path_inside(root, work / 'joined.mkv')
    else:
        invoke(payload, work, monitor, 300)
    result = read_json(output / 'result.json')
    check()
    worker.transition(record.job_id, JobStatus.VALIDATING)
    if operation == 'render':
        target = output / 'final.mp4'
        final = probe(target, work, check)
        from ..validation import validate_output
        validate_output(original, final, target.stat().st_size, record.options.video_codec, subtitle_mode='none')
        video = next(s for s in final['streams'] if s['codec_type'] == 'video')
        if int(video.get('nb_frames', 0)) != result['frame_count'] or abs(float(video.get('start_time', 0))) > .05:
            raise ValueError('최종 연결 영상의 프레임 수 또는 시작 타임스탬프가 일치하지 않습니다.')
        if abs(final['duration'] - original['duration']) > max(.5, original['duration'] * .001):
            raise ValueError('합성 결과의 영상 길이가 일치하지 않습니다.')
        if any(s['codec_type'] == 'audio' for s in original['streams']) and not any(s['codec_type'] == 'audio' for s in final['streams']):
            raise ValueError('합성 결과의 오디오가 없습니다.')
        validate_decodable(target, work, check)
        check()
        target.replace(root / 'output/final.mp4')
        worker.transition(record.job_id, JobStatus.COMPLETED,
                          metadata={'result_files': ['final.mp4'], 'duration': final['duration'], 'stage_progress': 1,
                                    'encoder': result['encoder'], 'output_bytes': (root / 'output/final.mp4').stat().st_size})
    else:
        files = []
        for image in output.glob('*.png'):
            image.replace(root / 'output' / image.name)
            files.append(image.name)
        worker.transition(record.job_id, JobStatus.COMPLETED,
                          metadata={'faceswap_result': result, 'faceswap_files': files, 'result_files': []})
