"""Public fixtures only. Compare cold CLI requests to reusable GPU inference."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

from video_service.faceswap import DEFAULTS
from video_service.storage import read_json, write_json_atomic
from media_agent.faceswap import runner
from media_agent.faceswap.process import run
from media_agent.faceswap.warm import release


def main():
    fixtures = Path(os.getenv('FACEFUSION_FIXTURES', '/fixtures'))
    python, engine, env = runner.environment()
    env['FACEFUSION_PARENT_PID'] = str(os.getpid())
    bridge = Path(runner.__file__).with_name('bridge.py')
    with tempfile.TemporaryDirectory(prefix='faceswap-benchmark-') as folder:
        root = Path(folder)
        def execute(payload, name, cold=False):
            work = root / name
            work.mkdir()
            payload = {**payload, 'output': str(work / 'output')}
            start = time.perf_counter()
            if cold:
                write_json_atomic(work / 'request.json', payload)
                run([str(python), '-B', str(bridge), '--engine', str(engine), '--request', str(work / 'request.json')],
                    cwd=engine, env=env, log=work / 'engine.log', check=lambda: None, timeout=180)
            else:
                runner.invoke(payload, work, lambda: None, 180)
            elapsed = round(time.perf_counter() - start, 3)
            result = read_json(work / 'output/result.json')
            print(json.dumps({'step': name, 'seconds': elapsed}), flush=True)
            return result, elapsed, work
        cap, _, _ = execute({'operation': 'capabilities'}, 'capabilities')
        payload = {'fingerprint': cap['fingerprint'], 'session_id': 'public-benchmark',
                   'source': str(fixtures / 'source.jpg'), 'target': str(fixtures / 'target.mp4'),
                   'settings': {**DEFAULTS, 'source_position': 0, 'face_position': 0}, 'preview_frame': 1}
        report = {}
        hashes = {}
        try:
            for mode in ('cold', 'warm'):
                release()
                samples = []
                for i, (operation, frame) in enumerate([('analyze_source', 1), ('analyze_reference', 1),
                                                       ('preview', 1), ('preview', 90), ('preview', 135)]):
                    result, seconds, work = execute({**payload, 'operation': operation, 'preview_frame': frame},
                                                     f'{mode}-{i}-{operation}', cold=mode == 'cold')
                    if operation == 'preview':
                        assert result['matched_faces'] >= 1
                        hashes[(mode, frame)] = hashlib.sha256((work / 'output/preview.png').read_bytes()).hexdigest()
                    samples.append(seconds)
                report[mode] = {'steps': samples, 'initial_pipeline_seconds': round(sum(samples[:3]), 3),
                                'subsequent_preview_seconds': samples[3:]}
            assert all(hashes['cold', f] == hashes['warm', f] for f in (1, 90, 135)), 'Cold/warm pixels differ'
            report['identical_preview_pixels'] = True
            print(json.dumps(report, indent=2), flush=True)
        finally:
            release()


if __name__ == '__main__':
    main()
