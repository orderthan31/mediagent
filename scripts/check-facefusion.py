"""Run with the installed FaceFusion Python; never installs or updates the engine.

The synthetic video exercises the headless pipeline, not face-swap quality.
Example (activate the engine environment first):
  python scripts/check-facefusion.py --engine <repo> --output <new-directory>
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zlib


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    engine = args.engine.resolve(strict=True)
    if not (engine / 'facefusion.py').is_file():
        parser.error('--engine must contain facefusion.py')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    # Scoped to this process/children; do not modify the installed environment.
    environment = Path(sys.executable).parent
    os.environ['PATH'] = os.pathsep.join([
        str(environment), str(environment / 'Library/bin'),
        str(environment / 'Scripts'), os.environ.get('PATH', '')])
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    report = {'engine': str(engine), 'python': sys.executable, 'checks': {},
              'limitations': ['Synthetic inputs: real-person swapping and multi-person selection are not tested.']}

    def run(name, command, timeout=300):
        started = time.monotonic()
        print(name, flush=True)
        with (output / (name + '.log')).open('wb') as log:
            result = subprocess.run(command, cwd=engine, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=timeout, check=False)
        report['checks'][name] = {'exit_code': result.returncode,
                                 'seconds': round(time.monotonic() - started, 2)}
        if result.returncode:
            raise RuntimeError(f'{name} failed: see {output / (name + ".log")}')

    try:
        ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
        if not ffmpeg or not ffprobe:
            raise RuntimeError('Activate the FaceFusion environment with FFmpeg/FFprobe first')
        base = [sys.executable, '-B', str(engine / 'facefusion.py')]
        run('version', base + ['--version'], 30)
        run('headless-help', base + ['headless-run', '--help'], 30)
        report['version'] = (output / 'version.log').read_text().strip()
        # Validate every model needed by the explicitly selected 3.5.4 defaults.
        # Refuse to proceed rather than let the engine repair/download a model.
        models = ['2dfan4', 'arcface_w600k_r50', 'bisenet_resnet_34', 'fairface',
                  'fan_68_5', 'hyperswap_1a_256', 'nsfw_1', 'nsfw_2', 'nsfw_3',
                  'xseg_1', 'yoloface_8n']
        if report['version'] != 'FaceFusion 3.5.4':
            raise RuntimeError('Review model requirements for this engine version before smoke testing')
        for model in models:
            path = engine / '.assets/models' / (model + '.onnx')
            crc = 0
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    crc = zlib.crc32(chunk, crc)
            if format(crc, '08x') != path.with_suffix('.hash').read_text().strip():
                raise RuntimeError(f'Installed model hash does not match: {model}')
        report['model_hashes'] = 'passed'
        run('cuda-inference', [sys.executable, '-B', '-u', '-c',
            "import numpy as n, onnxruntime as o; "
            "s=o.InferenceSession('.assets/models/hyperswap_1a_256.onnx',providers=['CUDAExecutionProvider']); "
            "print('ORT',o.__version__,'providers',s.get_providers(),flush=True); "
            "assert s.get_providers()[0]=='CUDAExecutionProvider','CUDA unavailable'; "
            "r=s.run(None,{'source':n.zeros((1,512),n.float32),'target':n.zeros((1,3,256,256),n.float32)}); "
            "assert all(n.isfinite(v).all() for v in r); print('outputs',[v.shape for v in r])"])
        source, result = output / 'synthetic.mp4', output / 'result.mp4'
        run('create-video', [ffmpeg, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
            'color=c=gray:s=320x240:r=5:d=1', '-f', 'lavfi', '-i',
            'sine=frequency=440:duration=1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-shortest', str(source)])
        run('headless-video', base + ['headless-run', '-t', str(source), '-o', str(result),
            '--jobs-path', str(output / 'jobs'), '--temp-path', str(output / 'temp'),
            '--processors', 'face_debugger', '--face-debugger-items', 'bounding-box',
            '--face-detector-model', 'yolo_face', '--face-landmarker-model', '2dfan4',
            '--face-occluder-model', 'xseg_1', '--face-parser-model', 'bisenet_resnet_34',
            '--execution-providers', 'cuda', '--execution-thread-count', '1',
            '--output-video-encoder', 'h264_nvenc', '--log-level', 'debug'])
        run('ffprobe', [ffprobe, '-v', 'error', '-show_streams', '-show_format',
                        '-of', 'json', str(result)])
        media = json.loads((output / 'ffprobe.log').read_text())
        assert {'video', 'audio'} <= {s['codec_type'] for s in media['streams']}
        assert abs(float(media['format']['duration']) - 1) < .3
        report['status'] = 'passed'
    except Exception as error:
        report['status'] = 'failed'
        report['error'] = str(error)
        raise
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
