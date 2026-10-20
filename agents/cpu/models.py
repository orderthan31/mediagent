"""CPU-only offline speech/model role broker, explicitly enabled by operator."""

from video_service.engine_service import model_main


def main(argv=None):
    return model_main(argv)
