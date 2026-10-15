from contextlib import ExitStack
from pathlib import Path
import os
import shutil
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / p) for p in ('apps/api', 'workers/media', 'packages/shared')]
from media_worker.faceswap.chunks import plan_chunks, assert_cfr, checksum, reusable
from media_worker.media import executable, probe
from media_worker.worker import Worker
from video_service.faceswap import digest, reservation
from video_service.models import JobStatus, QualityProfile
from video_service.repository import FilesystemJobRepository
from video_service.storage import write_json_atomic, read_json

FFMPEG = shutil.which('ffmpeg') or next((str(p) for p in (ROOT / '.tools').glob('ffmpeg-*/bin/ffmpeg.exe')), None)


class ChunkPlanTests(unittest.TestCase):
    def test_ten_minute_ranges_have_no_gaps_or_overlap(self):
        for fps in (5, 25, 30000 / 1001):
            plan = plan_chunks(100001, fps)
            self.assertEqual(plan[0]['start'], 0)
            self.assertEqual(plan[-1]['end'], 100001)
            self.assertEqual(sum(c['end'] - c['start'] for c in plan), 100001)
            for a, b in zip(plan, plan[1:]):
                self.assertEqual(a['end'], b['start'])
                self.assertAlmostEqual(a['start_seconds'] + a['duration'], b['start_seconds'])
            self.assertTrue(all(c['duration'] <= 600 for c in plan))

    def test_invalid_timeline_is_rejected(self):
        for total, fps, seconds in [(0, 30, 600), (10, float('nan'), 600), (10, 0, 600), (10, 30, 601)]:
            with self.assertRaises(ValueError):
                plan_chunks(total, fps, seconds)

    def test_reservation_limits_raw_frames_to_one_chunk(self):
        asset = {'size_bytes': 1000000, 'media': {'duration': 3600, 'width': 1920, 'height': 1080, 'frame_rate': '30/1'}}
        with patch.dict(os.environ, {'FACEFUSION_CHUNK_SECONDS': '600'}):
            self.assertLess(reservation(asset, True), 3600 * 60 * 1920 * 1080 * 4 / 3)


@unittest.skipUnless(FFMPEG, 'FFmpeg required')
class ChunkMediaTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / 'data/test-runs' / uuid4().hex
        self.repo = FilesystemJobRepository(self.root)
        self.addCleanup(shutil.rmtree, self.root)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {'FACEFUSION_ENABLED': 'true',
            'MIN_FREE_SPACE_BYTES': '0', 'VIDEO_ENCODER': 'libx264', 'FACEFUSION_CHUNK_SECONDS': '1'}))

    def test_vfr_rejected_and_fractional_tick_rounding_accepted(self):
        path = self.root / 'timeline.log'
        path.write_text('VFR:0.500000 (5/10) min: 100 max: 101 avg: 100')
        assert_cfr(path)
        path.write_text('VFR:0.500000 (5/10) min: 100 max: 200 avg: 150')
        with self.assertRaises(ValueError):
            assert_cfr(path)

    def test_tampered_completed_chunk_is_not_reused(self):
        path = self.root / 'chunk.mp4'
        path.write_bytes(b'first')
        entry = {'status': 'completed', 'size': 5, 'sha256': checksum(path, lambda: None)}
        self.assertTrue(reusable(entry, path, lambda: None))
        path.write_bytes(b'other')
        self.assertFalse(reusable(entry, path, lambda: None))

    def test_resume_completed_chunks_and_merge_audio_timeline(self):
        job = self.repo.create_job(original_filename='test.mp4', expected_size=1,
            source_language='en', target_language='ko', quality_profile=QualityProfile.BALANCED)
        source = self.repo.source_path(job)
        subprocess.run([FFMPEG, '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=s=160x120:r=5:d=3',
            '-itsoffset', '0.4', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2.6', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', str(source)], check=True)
        snapshot = {'source_sha256': None, 'fingerprint': 'test', 'settings': {'video_codec': 'h264'}}
        job.options.video_codec = 'h264'
        job.metadata.update(faceswap=snapshot, faceswap_key=digest(snapshot), faceswap_operation='render',
                            preview_frame=1, faceswap_chunk_seconds=1)
        job.expected_size = job.uploaded_bytes = source.stat().st_size
        self.repo.save(job)
        self.repo.update_status(job.job_id, JobStatus.QUEUED)
        write_json_atomic(self.repo.job_dir(job.job_id) / 'input/faceswap.json', snapshot)
        calls = []
        fail = True
        def engine(payload, work, check, timeout):
            output = Path(payload['output'])
            output.mkdir(parents=True)
            if payload['operation'] == 'inspect_video':
                write_json_atomic(output / 'result.json', {'frame_count': 15, 'fps': 5})
                return
            chunk = payload['chunk']
            calls.append(chunk['index'])
            (work / 'temp').mkdir()
            (work / 'temp/frame.png').write_bytes(b'disposable')
            if fail and chunk['index'] == 1:
                raise RuntimeError('simulated engine failure')
            subprocess.run([FFMPEG, '-v', 'error', '-i', payload['target'], '-an', '-vf',
                f"trim=start_frame={chunk['start']}:end_frame={chunk['end']},setpts=PTS-STARTPTS",
                '-c:v', 'libx264', str(output / 'final.mp4')], check=True)
            write_json_atomic(output / 'result.json', {'file': 'final.mp4'})
        factory = Mock(side_effect=AssertionError('No LLM calls'))
        with patch('media_worker.faceswap.runner.invoke', side_effect=engine):
            worker = Worker(self.repo, None, provider_factory=factory)
            worker.process(job.job_id)
            self.assertEqual(self.repo.read(job.job_id).status, JobStatus.FAILED)
            cache = next((self.repo.job_dir(job.job_id) / 'work').glob('faceswap-chunks-*'))
            state = read_json(cache / 'queue.json')
            self.assertEqual([c['status'] for c in state['chunks']], ['completed', 'failed', 'pending'])
            self.assertFalse(list(cache.glob('attempt-*/temp')))
            first_hash = checksum(cache / 'chunk-00000.mp4', lambda: None)
            fail = False
            self.repo.update_status(job.job_id, JobStatus.QUEUED)
            worker.process(job.job_id)
        finished = self.repo.read(job.job_id)
        self.assertEqual(finished.status, JobStatus.COMPLETED, finished.error)
        self.assertEqual(calls, [0, 1, 1, 2])
        self.assertEqual(checksum(cache / 'chunk-00000.mp4', lambda: None), first_hash)
        self.assertFalse(list(cache.glob('attempt-*/temp')))
        output = self.repo.job_dir(job.job_id) / 'output/final.mp4'
        metadata = probe(output, self.root)
        video = next(s for s in metadata['streams'] if s['codec_type'] == 'video')
        self.assertEqual(int(video['nb_frames']), 15)
        self.assertAlmostEqual(float(video['start_time']), 0, places=3)
        self.assertLess(abs(metadata['duration'] - 3), .1)
        self.assertTrue(any(s['codec_type'] == 'audio' for s in metadata['streams']))
        # Preserve the source's delayed audio start and avoid silence at chunk seams.
        import array
        audio = subprocess.run([FFMPEG, '-v', 'error', '-i', str(output), '-vn', '-ac', '1', '-ar', '16000',
            '-f', 's16le', 'pipe:1'], check=True, capture_output=True).stdout
        samples = array.array('h', audio)
        def energy(start, end):
            segment = samples[int(start * 16000):int(end * 16000)]
            return sum(abs(v) for v in segment) / len(segment)
        self.assertLess(energy(.1, .2), 10)
        self.assertGreater(energy(.6, .7), 100)
        self.assertGreater(energy(.95, 1.05), 100)
        self.assertGreater(energy(1.95, 2.05), 100)
        self.assertEqual(finished.metadata['faceswap_chunks']['completed'], 3)
        factory.assert_not_called()

    def test_fractional_fps_silent_video_has_continuous_timestamps(self):
        import json
        fps = 30000 / 1001
        job = self.repo.create_job(original_filename='fractional.mp4', expected_size=1,
            source_language='en', target_language='ko', quality_profile=QualityProfile.BALANCED)
        source = self.repo.source_path(job)
        subprocess.run([FFMPEG, '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=s=160x120:r=30000/1001',
            '-frames:v', '61', '-c:v', 'libx264', str(source)], check=True)
        snapshot = {'source_sha256': None, 'fingerprint': 'test', 'settings': {'video_codec': 'h264'}}
        job.options.video_codec = 'h264'
        job.metadata.update(faceswap=snapshot, faceswap_key=digest(snapshot), faceswap_operation='render',
                            preview_frame=1, faceswap_chunk_seconds=1)
        self.repo.save(job)
        self.repo.update_status(job.job_id, JobStatus.QUEUED)
        write_json_atomic(self.repo.job_dir(job.job_id) / 'input/faceswap.json', snapshot)
        def engine(payload, work, check, timeout):
            output = Path(payload['output'])
            output.mkdir(parents=True)
            if payload['operation'] == 'inspect_video':
                write_json_atomic(output / 'result.json', {'frame_count': 61, 'fps': fps})
                return
            chunk = payload['chunk']
            subprocess.run([FFMPEG, '-v', 'error', '-i', payload['target'], '-an', '-vf',
                f"trim=start_frame={chunk['start']}:end_frame={chunk['end']},setpts=PTS-STARTPTS",
                '-c:v', 'libx264', str(output / 'final.mp4')], check=True)
            write_json_atomic(output / 'result.json', {'file': 'final.mp4'})
        with patch('media_worker.faceswap.runner.invoke', side_effect=engine):
            Worker(self.repo, None).process(job.job_id)
        finished = self.repo.read(job.job_id)
        self.assertEqual(finished.status, JobStatus.COMPLETED, finished.error)
        target = self.repo.job_dir(job.job_id) / 'output/final.mp4'
        result = subprocess.run([executable('ffprobe'), '-v', 'error', '-select_streams', 'v:0',
            '-show_frames', '-show_entries', 'frame=best_effort_timestamp_time', '-of', 'json', str(target)],
            check=True, capture_output=True, text=True)
        times = [float(f['best_effort_timestamp_time']) for f in json.loads(result.stdout)['frames']]
        self.assertEqual(len(times), 61)
        self.assertAlmostEqual(times[0], 0, places=5)
        for first, second in zip(times, times[1:]):
            self.assertAlmostEqual(second - first, 1 / fps, places=5)
        self.assertFalse(any(s['codec_type'] == 'audio' for s in probe(target, self.root)['streams']))


if __name__ == '__main__':
    unittest.main()
