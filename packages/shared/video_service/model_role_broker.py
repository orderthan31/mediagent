"""Legacy import; implementation lives in mideagent_orchestrator.model_transport."""
import sys
from importlib import import_module
sys.modules[__name__]=import_module('mideagent_orchestrator.model_transport')
