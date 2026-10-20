"""Parse deployment recipes without starting any service or reading private values."""

import json
import os
import subprocess
import unittest
from pathlib import Path


class ComposeMountTests(unittest.TestCase):
    def test_every_tmpfs_entry_is_one_absolute_mount(self):
        root = Path(__file__).resolve().parents[1]
        env = {
            **os.environ,
            "MIDEAGENT_BOOTSTRAP_DIR": str(root / "not-an-installed-bootstrap"),
            "MIDEAGENT_AGENT_NETWORK": "review-only-no-network-created",
        }
        recipes = [
            ("docker-compose.yml",),
            ("docker-compose.yml", "compose.windows.yaml"),
            ("infra/compose.yaml",),
            ("docker-compose.yml", "compose.transport.yaml"),
            ("agents/cpu/compose.amqp.yaml",),
        ]
        for files in recipes:
            args = ["docker", "compose", "--profile", "*"]
            for file in files:
                args.extend(["-f", str(root / file)])
            result = subprocess.run(
                [*args, "config", "--format", "json"],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            services = json.loads(result.stdout)["services"]
            if "api" in services:
                source = next(
                    m["source"]
                    for m in services["api"]["volumes"]
                    if m["target"] == "/run/bootstrap"
                )
                self.assertTrue(source.replace("\\", "/").endswith("/api"))
            if "compose.windows.yaml" in files:
                self.assertEqual(services["web"]["ports"][0]["published"], "5177")
                self.assertEqual(services["web"]["ports"][0]["host_ip"], "127.0.0.1")
            if "results" in services:
                mounts = services["results"].get("tmpfs", [])
                self.assertTrue(
                    any(mount.startswith("/data/content:") for mount in mounts),
                    "result consumer needs its private writable S3 cache",
                )
            for service, value in json.loads(result.stdout)["services"].items():
                for mount in value.get("tmpfs", []):
                    self.assertTrue(mount.startswith("/"), (files, service, mount))


if __name__ == "__main__":
    unittest.main()
