"""Extend only a disposable bootstrap tree; do not rotate existing secrets."""

import hashlib, json, re, tempfile, unittest
from pathlib import Path


class EngineProvisionTests(unittest.TestCase):
    def test_provision_cli_requires_explicit_apply(self):
        from app.engine_admin import main
        import contextlib, io

        with (
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit) as error,
        ):
            main(
                [
                    "provision",
                    "--directory",
                    "/missing",
                    "--manifest-file",
                    "/missing.json",
                ]
            )
        self.assertEqual(error.exception.code, 2)

    def test_additive_role_credentials_and_no_secret_rotation(self):
        from app.bootstrap import generate
        from app.engine_admin import provision

        def hashes(root):
            return {
                str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in root.rglob("*")
                if p.is_file()
            }

        manifests = {}
        for role, engine, family, source, target in [
            ("transcribe", "whisper-tiny-en", "model", "en", None),
            ("translate", "opus-en-de-int8", "model", "en", "de"),
            ("preprocess_audio", "nvidia-marblenet", "gpu", None, None),
            ("faceswap", "facefusion-3.9.0", "gpu", None, None),
        ]:
            manifests[role] = {
                "descriptor": {
                    "role": role,
                    "family": family,
                    "engine": engine,
                    "model_sha256": "a" * 64,
                    "source_language": source,
                    "target_language": target,
                },
                "model_dir": "/models",
            }
            if role == "faceswap":
                manifests[role]["python"] = "/opt/facefusion-env/bin/python"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "bootstrap"
            generate(root, "https://fixture.invalid")
            before = hashes(root)
            result = provision(root, manifests)
            after = hashes(root)
            modified = {name for name, sha in before.items() if after[name] != sha}
            self.assertEqual(
                modified,
                {"api/api.json", "operator/api.json", "broker/definitions.json"},
            )
            self.assertEqual(result["engine_roles"], sorted(manifests))
            from app.server import load_bootstrap

            probe = json.loads((root / "operator/api.json").read_bytes())
            probe["database_dsn_file"] = str(root / "operator/database-dsn")
            probe_path = root / "loader-probe.json"
            probe_path.write_text(json.dumps(probe))
            self.assertIn("engine_broker_config_file", load_bootstrap(probe_path)[0])
            from app.operator import runtime_components

            objects = json.loads((root / "operator/objects.json").read_bytes())
            objects.update(
                access_key_file=str(root / "operator/objects-user"),
                secret_key_file=str(root / "operator/objects-password"),
                cache_root=str(root / "cache"),
            )
            objects_path = root / "objects-probe.json"
            objects_path.write_text(json.dumps(objects))
            probe.update(
                object_config_file=str(objects_path),
                broker_config_file=str(root / "operator/operator-broker.json"),
                engine_broker_config_file=str(root / "operator/engine-broker.json"),
            )
            _, _, factory = runtime_components(None, probe, enable_broker=True)
            self.assertTrue(callable(getattr(factory, "engine_factory", None)))
            self.assertEqual(provision(root, manifests)["files_written"], 0)
            definitions = json.loads((root / "broker/definitions.json").read_text())
            permission = next(
                p for p in definitions["permissions"] if p["user"] == "engine_faceswap"
            )
            self.assertTrue(
                re.fullmatch(permission["read"], "mideagent.engine.faceswap.v2")
            )
            self.assertFalse(
                re.fullmatch(permission["read"], "mideagent.engine.transcribe.v2")
            )
            self.assertFalse(
                re.fullmatch(permission["write"], "mideagent.engine.commands.v2")
            )
            for role in manifests:
                folder = root / "agent/engine" / role
                self.assertTrue((folder / "runtime.json").is_file())
                self.assertFalse((folder / "database-dsn").exists())
                self.assertFalse((folder / "credential-master.key").exists())
            invalid = {key: {**value} for key, value in manifests.items()}
            invalid["transcribe"] = {
                **invalid["transcribe"],
                "model_dir": "/different-location",
            }
            stable = hashes(root)
            with self.assertRaises(ValueError):
                provision(root, invalid)
            self.assertEqual(hashes(root), stable)


if __name__ == "__main__":
    unittest.main()
