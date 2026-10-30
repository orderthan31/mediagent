"""Compatibility CLI; implementation: mideagent_orchestrator.operator."""
import sys
from importlib import import_module
_implementation=import_module("mideagent_orchestrator.operator")
if __name__=="__main__":
    raise SystemExit(_implementation.main())
else:
    sys.modules[__name__]=_implementation
