import contextlib, io, unittest


class EngineEntryPointTests(unittest.TestCase):
    def test_preprocess_console_alias_uses_real_cpu_parser(self):
        import runpy, sys
        from pathlib import Path
        from unittest.mock import patch

        module = runpy.run_path(
            str(Path(__file__).resolve().parents[1] / "agents/cpu/cli.py")
        )
        with (
            patch.object(sys, "argv", ["mideagent-preprocess-audio", "--help"]),
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaises(SystemExit) as error,
        ):
            module["preprocess_audio"]()
        self.assertEqual(error.exception.code, 0)

    def test_broker_consumption_needs_explicit_flag_and_matching_family(self):
        from video_service.engine_service import model_main, gpu_main

        files = [
            "--broker-config-file",
            "/missing/broker.json",
            "--object-config-file",
            "/missing/objects.json",
            "--runtime-config-file",
            "/missing/runtime.json",
        ]
        for function, role in [(model_main, "transcribe"), (gpu_main, "faceswap")]:
            with (
                self.subTest(role=role),
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as error,
            ):
                function(["--agent", role, *files])
            self.assertEqual(error.exception.code, 2)
        with (
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit) as error,
        ):
            model_main(["--enable-broker", "--agent", "faceswap", *files])
        self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
