"""GPU-only role broker. Never imports the legacy media Worker/controller."""

from video_service.engine_service import gpu_main


def main(argv=None):
    return gpu_main(argv)
