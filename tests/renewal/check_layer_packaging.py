"""Offline source/package checks. No server, provider, container or GPU execution."""
from pathlib import Path
import re
import unittest
ROOT=Path(__file__).resolve().parents[2]
class LayerPackaging(unittest.TestCase):
 def test_cpu_compose_build_paths_exist(self):
  for rel in ["tools/media/compose.yaml","tools/media/compose.amqp.yaml"]:
   text=(ROOT/rel).read_text()
   for path in re.findall(r"dockerfile:\s*(\S+)",text):
    self.assertTrue((ROOT/path).is_file(),rel+": "+path)
 def test_local_api_install_closure(self):
  for rel in ["README.md",".github/workflows/docker.yml"]:
   line=next(l for l in (ROOT/rel).read_text().splitlines()if "pip install"in l and "-e apps/api"in l)
   for path in ["agents","apps/orchestrator","packages/tool-hub","tools/models","runtime/controlnet"]:
    self.assertRegex(line,r"-e\s+"+re.escape(path)+r"(?:\s|$)",rel+": "+path)
 def test_gpu_region_tool_has_media_dependency(self):
  root=ROOT/("tools/gpu"if(ROOT/"tools/gpu").exists()else"agents/gpu")
  broker=(root/"Dockerfile").read_text().split("AS broker",1)[1]
  self.assertIn("COPY tools/media",broker)
  self.assertIn("/app/tools/media",broker)
 def test_agents_directory_contains_business_implementation_only(self):
  self.assertFalse((ROOT/"agents/gpu").exists(),"GPU adapters are tools, not business agents")
if __name__=="__main__":unittest.main()
