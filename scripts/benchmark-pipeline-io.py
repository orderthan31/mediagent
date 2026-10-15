"""Read-only library metadata benchmark, processing synthetic media only.

Run in an isolated worker container with the repository mounted at /candidate
and the production library mounted READ ONLY at /library.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def measured(function):
    start = time.monotonic()
    result = function()
    return result, round(time.monotonic() - start, 3)


def child(mode):
    if mode == 'candidate':
        sys.path[:0] = ['/candidate/workers/media', '/candidate/packages/shared']
    from video_service.capacity import used_bytes
    from media_worker.worker_storage import capacity_estimate, check_capacity
    from media_worker.media import probe, extract_audio, preprocess_audio
    from media_worker.validation import validate_decodable
    root = Path('/library')
    work = Path('/tmp/pipeline-benchmark') / mode
    work.mkdir(parents=True, exist_ok=True)
    fixture = Path('/tmp/pipeline-benchmark/synthetic.mp4')
    count, scan = measured(lambda: used_bytes(root))
    def check():
        check_capacity(root, 10**15, 0)
    with capacity_estimate(root):
        _, metadata = measured(lambda: probe(fixture, work, check))
        audio, extraction = measured(lambda: extract_audio(fixture, work, check))
        _, preprocessing = measured(lambda: preprocess_audio(audio, work, check, audio_filter='off'))
        _, validation = measured(lambda: validate_decodable(fixture, work, check))
    print(json.dumps({'mode': mode, 'library_bytes': count, 'scan_seconds': scan,
        'analysis_seconds': metadata, 'extract_seconds': extraction,
        'preprocess_seconds': preprocessing, 'validation_seconds': validation}))


if __name__ == '__main__':
    if len(sys.argv) == 2:
        child(sys.argv[1])
    else:
        work = Path('/tmp/pipeline-benchmark')
        work.mkdir(exist_ok=True)
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
            'testsrc2=size=1280x720:rate=30', '-f', 'lavfi', '-i', 'sine=frequency=440',
            '-t', '10', '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac',
            str(work / 'synthetic.mp4')], check=True)
        for mode in ('baseline', 'candidate'):
            subprocess.run([sys.executable, __file__, mode], check=True)
