"""Compatibility boundary only. Canonical implementation: mideagent_tool_hub.registry."""
import sys as _sys
from importlib import import_module as _import_module
_implementation = _import_module("mideagent_tool_hub.registry")
if __name__ == "__main__":
    _main=getattr(_implementation,"main",None)
    if _main is not None:
        raise SystemExit(_main())
else:
    _sys.modules[__name__] = _implementation
