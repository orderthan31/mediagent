"""Source recipe and real local fixture checks; never invoke Docker or pip."""

import shlex
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime/model-executor"
PROJECTS = {
    "/app/packages/shared", "/app/packages/tool-hub", "/app/agents",
    "/app/tools/media", "/app/tools/models", "/app/runtime/model-executor",
}


def instructions():
    source = (RUNTIME / "Dockerfile").read_text(encoding="utf-8")
    lines = source.replace("\\\n", " ").splitlines()
    return [line.strip().split(None, 1) for line in lines if line.strip() and not line.lstrip().startswith("#")]


def commands():
    result = []
    for instruction, value in instructions():
        if instruction != "RUN":
            continue
        for command in value.split("&&"):
            result.append(shlex.split(command.strip()))
    return result


def pip_commands():
    result = []
    for command in commands():
        if command[:3] == ["python", "-m", "pip"]:
            result.append(command)
        elif command[:1] == ["pip"]:
            result.append(["python", "-m", "pip", *command[1:]])
    return result


def graph_install():
    return next((command for command in pip_commands() if "--requirement" in command), None)


def test_graph_install_uses_original_base_constraints_before_any_install():
    recipe = pip_commands()
    captures = [command for command in recipe if "freeze" in command]
    assert len(captures) == 1, "capture installed base versions before changing dependencies"
    capture = captures[0]
    assert "--all" in capture
    constraints = capture[capture.index(">") + 1]
    graph = graph_install()
    assert graph is not None, "install the declared graph requirements in the shipped image"
    assert graph[graph.index("--requirement") + 1] == "/app/runtime/model-executor/requirements.txt"
    assert graph[graph.index("--constraint") + 1] == constraints
    assert "--no-deps" not in graph, "resolve required graph transitive dependencies"
    assert "--upgrade" not in graph and "--ignore-installed" not in graph
    assert recipe.index(capture) < min(i for i, command in enumerate(recipe) if "install" in command)


def test_current_same_version_local_packages_are_reinstalled_without_dependency_changes():
    local = [command for command in pip_commands() if PROJECTS <= set(command)]
    assert len(local) == 1, "reinstall every current local project, including existing 0.1 versions"
    assert {"--force-reinstall", "--no-deps"} <= set(local[0])
    graph = graph_install()
    assert graph is not None and pip_commands().index(graph) < pip_commands().index(local[0])


def test_local_source_build_provisions_backend_without_preinstalled_base_tooling():
    local = [command for command in pip_commands() if PROJECTS <= set(command)]
    assert len(local) == 1
    # The original base has no setuptools/wheel. Standard PEP 517 isolation
    # provisions build backends temporarily; --no-deps still fences runtime deps.
    assert "--no-build-isolation" not in local[0], (
        "local source builds must provision their backend in an isolated build environment"
    )


def test_nonroot_smoke_imports_installed_asr_and_mt_without_source_path_fallback():
    current_user = None
    smoke = []
    for instruction, value in instructions():
        if instruction == "USER":
            current_user = value
        if instruction == "RUN" and "import mideagent_model_runtime.broker" in value:
            smoke.append(value)
            assert current_user == "10001:10001"
            assert shlex.split(value)[:3] == ["python", "-I", "-c"]
            assert "mideagent_agents.transcription.model_graph" in value
            assert "mideagent_agents.translation.model_graph" in value
    assert len(smoke) == 1


def test_declared_requirement_versions_remain_exactly_pinned():
    pins = (RUNTIME / "requirements.txt").read_text(encoding="utf-8").splitlines()
    assert pins == [
        "langgraph==1.2.18", "langgraph-checkpoint-sqlite==3.1.2",
        "langchain-core==1.7.0", "pydantic==2.14.1",
    ]


def test_graph_fixture_creates_existing_private_root_without_relaxing_store_guard(tmp_path):
    from graph_execution import private_content_store
    from video_service.content_store import ContentStore

    store = private_content_store(tmp_path)
    assert store.root == (tmp_path / "content").resolve(strict=True)
    assert store.root.is_dir() and not store.root.is_symlink()
    with pytest.raises(ValueError, match="Explicit existing private content root required"):
        ContentStore(tmp_path / "still-missing")
