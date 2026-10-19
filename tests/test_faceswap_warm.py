import os
from pathlib import Path
import shutil
import sys
import time
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / p) for p in ('packages/shared', 'agents/media')]
from media_agent.faceswap.warm import WarmEngine
from video_service.storage import read_json


class WarmEngineTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / 'data/test-runs' / uuid4().hex
        self.root.mkdir(parents=True)
        self.addCleanup(self.remove_root)
        script = self.root / 'engine.py'
        script.write_text('''import json,sys,time,os
from pathlib import Path
folder=Path(sys.argv[-1]); count=0
while True:
    inbox=folder/'inbox.json'
    if not inbox.exists():
        time.sleep(.01); continue
    msg=json.loads(inbox.read_text()); inbox.unlink()
    req=json.loads(Path(msg['request']).read_text()); count+=1
    if req.get('hang'): time.sleep(60)
    output=Path(req['output']); output.mkdir(parents=True,exist_ok=True)
    (output/'result.json').write_text(json.dumps({'count':count,'pid':os.getpid()}))
    dest=Path(msg['response']); tmp=dest.with_suffix('.tmp')
    tmp.write_text(json.dumps({'ok':not req.get('fail')})); tmp.replace(dest)
''', encoding='utf-8')
        self.engine = WarmEngine([sys.executable, str(script)], cwd=self.root, env=os.environ.copy(),
                                 directory=self.root / 'resident', idle_seconds=2)
        self.addCleanup(self.engine.close)

    def remove_root(self):
        # Windows may briefly retain redirected output handles after process exit.
        self.assertEqual(self.root.resolve().parent, (ROOT / 'data/test-runs').resolve())
        for attempt in range(20):
            try:
                shutil.rmtree(self.root)
                return
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(.05)

    def invoke(self, **extra):
        work = self.root / uuid4().hex
        work.mkdir()
        self.engine.invoke({'output': str(work / 'output'), **extra}, work, lambda: None, 5)
        return read_json(work / 'output/result.json')

    def test_reuses_process_and_serializes_distinct_results(self):
        first = self.invoke()
        second = self.invoke()
        self.assertEqual(first['pid'], second['pid'])
        self.assertEqual((first['count'], second['count']), (1, 2))
        self.engine.close()
        self.assertFalse(self.engine.alive)

    def test_failure_releases_engine(self):
        with self.assertRaises(RuntimeError):
            self.invoke(fail=True)
        self.assertFalse(self.engine.alive)

    def test_timeout_stops_process(self):
        work = self.root / 'timeout'
        work.mkdir()
        with self.assertRaises(TimeoutError):
            self.engine.invoke({'output': str(work), 'hang': True}, work, lambda: None, .3)
        self.assertFalse(self.engine.alive)

    def test_cancellation_stops_process_without_waiting_for_inference(self):
        work = self.root / 'cancel'
        work.mkdir()
        started = time.monotonic()
        def check():
            if time.monotonic() - started > .2:
                raise InterruptedError('cancel')
        with self.assertRaises(InterruptedError):
            self.engine.invoke({'output': str(work), 'hang': True}, work, check, 5)
        self.assertFalse(self.engine.alive)

    def test_idle_engine_releases_memory(self):
        self.invoke()
        self.engine.thread.join(timeout=4)
        self.assertFalse(self.engine.alive)
