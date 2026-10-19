"""One serialized, reusable engine with the same process-tree guarantees as CLI jobs."""
import atexit
import threading
import time
import tempfile
from pathlib import Path
from uuid import uuid4

from video_service.storage import read_json, write_json_atomic
from .process import run


class WarmEngine:
    def __init__(self, command, *, cwd, env, directory, idle_seconds=180):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.stop = threading.Event()
        self.error = None
        self.lock = threading.Lock()
        self.last_used = time.monotonic()
        self.idle_seconds = idle_seconds
        self.busy = False

        def check():
            if self.stop.is_set() or (not self.busy and time.monotonic() - self.last_used > idle_seconds):
                raise InterruptedError('Preview engine released')

        def supervise():
            try:
                run([*command, '--serve', str(self.directory)], cwd=cwd, env=env,
                    log=self.directory / 'engine.log', check=check, timeout=86400)
            except BaseException as exc:
                # Do not retain subprocess/file handles via exception tracebacks.
                self.error = RuntimeError(str(exc))

        self.thread = threading.Thread(target=supervise, name='faceswap-preview-engine', daemon=True)
        self.thread.start()

    @property
    def alive(self):
        return self.thread.is_alive() and not self.stop.is_set()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=10)
        if self.thread.is_alive():
            raise RuntimeError('Preview engine did not stop')

    def invoke(self, payload, work, check, timeout):
        with self.lock:
            check()
            self.busy = True
            started = time.monotonic()
            identity = uuid4().hex
            request_path = (work / 'request.json').resolve()
            response_path = self.directory / (identity + '.json')
            write_json_atomic(request_path, payload)
            try:
                write_json_atomic(self.directory / 'inbox.json', {
                    'id': identity, 'request': str(request_path), 'response': str(response_path.resolve())})
                while not response_path.exists():
                    check()
                    if not self.alive:
                        raise RuntimeError('FaceFusion 미리보기 엔진이 종료되었습니다. 다시 시도하세요.') from self.error
                    if time.monotonic() - started > timeout:
                        raise TimeoutError('FaceFusion 미리보기 제한 시간을 초과했습니다.')
                    time.sleep(.025)
                check()
                result = read_json(response_path)
                if not result['ok']:
                    raise RuntimeError('FaceFusion 처리가 실패했습니다. 입력 얼굴과 엔진 로그를 확인하세요.')
            except BaseException:
                # A failed/cancelled operation cannot contaminate the next request.
                self.close()
                raise
            finally:
                response_path.unlink(missing_ok=True)
                self.last_used = time.monotonic()
                self.busy = False
                log = self.directory / 'engine.log'
                if log.exists():
                    with log.open('rb') as stream:
                        stream.seek(max(0, log.stat().st_size - 65536))
                        (work / 'engine.log').write_bytes(stream.read())


_engine = None
_key = None
_directory = None


def release():
    global _engine, _key, _directory
    if _engine is not None:
        _engine.close()
        _engine = None
        _key = None
    if _directory is not None:
        _directory.cleanup()
        _directory = None


def invoke(payload, work, check, timeout, *, python, engine, env):
    global _engine, _key, _directory
    # The bridge clears image/face caches across sessions. Model weights are reusable.
    key = (str(python), str(engine), payload.get('fingerprint'))
    if _engine is None or not _engine.alive or _key != key:
        release()
        _directory = tempfile.TemporaryDirectory(prefix='faceswap-preview-')
        directory = Path(_directory.name)
        _engine = WarmEngine([str(python), '-B', str(Path(__file__).with_name('bridge.py')), '--engine', str(engine)],
                             cwd=engine, env=env, directory=directory)
        _key = key
    _engine.invoke(payload, work, check, timeout)


atexit.register(release)
