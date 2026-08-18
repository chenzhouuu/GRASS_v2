"""Python code execution tool for GRASS agents.

Writes code to a file and executes it, capturing stdout and stderr.
Agents inject concrete data-file paths into their prompts so executed
code can load inputs with ``pd.read_json``: retrieval steps live as
named workspace tables (``data/outputs/<session>/tables/``, see
session_workspace.py) and the optimizer's merged input at
``data/outputs/<session>/optimization_input.json``. Without a session id
the legacy shared path ``data/cypher_results.json`` is used
(benchmarks, tests).

Execution backend (``GRASS_PYTHON_SANDBOX`` env var):
- ``docker`` (default): the script runs in a locked-down container
  (``GRASS_SANDBOX_IMAGE``, default ``grass-sandbox:latest``) — no
  network, read-only root fs, capability-dropped, resource-limited.
  Only the calling session's ``data/outputs/<session>/`` directory is
  mounted (see ``execution_session``), at the same relative path as on
  the host, so the paths baked into prompts work unchanged — while the
  rest of ``data/`` and other sessions' files never enter the
  container. Missing image is a hard
  error, never a silent unsandboxed fallback.
- ``subprocess``: legacy direct execution with the server's own
  interpreter (tests, benchmarks, hosts without Docker).
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Annotated, Iterator, Optional

from langchain_core.tools import tool

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
)
os.makedirs(DATA_DIR, exist_ok=True)

PROJECT_ROOT = os.path.dirname(DATA_DIR)

TIMEOUT_SECONDS = 120
MAX_OUTPUT_CHARS = 30_000

SANDBOX_MODE_ENV = "GRASS_PYTHON_SANDBOX"
SANDBOX_IMAGE_ENV = "GRASS_SANDBOX_IMAGE"
DEFAULT_SANDBOX_IMAGE = "grass-sandbox:latest"

_EXECUTION_SESSION: ContextVar[Optional[str]] = ContextVar(
    "grass_execution_session", default=None
)


@contextmanager
def execution_session(session_id: Optional[str]) -> Iterator[None]:
    """Bind the session whose data directory the sandbox may mount.

    Agents wrap their ``execute_python`` invocations with this so the
    container sees only ``data/outputs/<session>/``. A ContextVar (not a
    module global) so concurrent runs in one server process cannot bleed
    into each other. ``None`` selects the legacy shared-file mounts.
    """
    token = _EXECUTION_SESSION.set(session_id)
    try:
        yield
    finally:
        _EXECUTION_SESSION.reset(token)


def sanitize_session_id(session_id: str) -> str:
    """Make a client-supplied session id safe to use as a directory name."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", session_id)


def cypher_results_path(session_id: Optional[str] = None) -> str:
    """Relative path (from project root) of the session's data file.

    Per-session isolation: two concurrent sessions must never read each
    other's rows. Generated code runs with the project root as its working
    directory, so this relative path is what agents substitute into prompts.
    The session id is sanitized because it arrives from the client API.
    """
    if session_id:
        return f"data/outputs/{sanitize_session_id(session_id)}/cypher_results.json"
    return "data/cypher_results.json"


def optimization_input_path(session_id: Optional[str] = None) -> str:
    """Relative path of the merged row file optimization code reads.

    The Optimization Agent's generated code — and the scenario engine's
    cached-code re-runs — load one flat input file whose path is baked in
    at codegen time, so writer and re-runner must derive it identically.
    """
    if session_id:
        return (
            f"data/outputs/{sanitize_session_id(session_id)}/optimization_input.json"
        )
    return "data/cypher_results.json"


def _persist(rel_path: str, records: list[dict]) -> str:
    abs_path = os.path.join(PROJECT_ROOT, rel_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, default=str)
    return rel_path


def persist_cypher_results(
    records: list[dict], session_id: Optional[str] = None
) -> str:
    """Write cypher_results to the session's JSON file.

    Returns the project-root-relative path to the written file (the same
    string agents inject into prompts).
    """
    return _persist(cypher_results_path(session_id), records)


def persist_optimization_input(
    rows: list[dict],
    session_id: Optional[str] = None,
    rel_path: Optional[str] = None,
) -> str:
    """Write the optimizer's flat input rows; returns the relative path.

    ``rel_path`` overrides the derived path: scenario re-solves must write
    to the exact path recorded in the baseline snapshot, because that path
    is baked into the baseline's cached code.
    """
    return _persist(rel_path or optimization_input_path(session_id), rows)


def _sandbox_mounts() -> list[str]:
    """Volume args giving the container the narrowest data view.

    Session bound (``execution_session``) → only that session's output
    directory, read-write, at the same relative path the prompts bake in.
    No session (benchmarks, legacy callers) → the shared ``data/outputs``
    directory plus the legacy ``data/cypher_results.json`` read-only.
    The ``data/`` root itself (configs, archived artifacts) is never
    mounted in either case. Host directories are
    pre-created because Docker would create missing ones root-owned.
    """
    session_id = _EXECUTION_SESSION.get()
    if session_id:
        safe = sanitize_session_id(session_id)
        host_dir = os.path.join(DATA_DIR, "outputs", safe)
        os.makedirs(host_dir, exist_ok=True)
        return ["-v", f"{host_dir}:/workspace/data/outputs/{safe}"]

    outputs_dir = os.path.join(DATA_DIR, "outputs")
    os.makedirs(outputs_dir, exist_ok=True)
    mounts = ["-v", f"{outputs_dir}:/workspace/data/outputs"]
    legacy = os.path.join(DATA_DIR, "cypher_results.json")
    if os.path.exists(legacy):
        mounts += ["-v", f"{legacy}:/workspace/data/cypher_results.json:ro"]
    return mounts


def _run_sandboxed(code_path: str) -> subprocess.CompletedProcess:
    """Run the script in a locked-down Docker container.

    The container mounts the script read-only and the session-scoped
    data view from ``_sandbox_mounts()``, so the relative paths baked
    into agent prompts resolve identically to host execution. On
    timeout the named container is force-removed before re-raising
    (killing the ``docker run`` client alone would leave it running).
    """
    image = os.environ.get(SANDBOX_IMAGE_ENV, DEFAULT_SANDBOX_IMAGE)
    name = f"grass-sbx-{uuid.uuid4().hex[:12]}"
    cmd = [
        "docker", "run", "--rm", "--name", name,
        "--network=none",
        "--memory=2g", "--cpus=2", "--pids-limit=256",
        "--read-only", "--tmpfs", "/tmp:size=256m",
        "--cap-drop=ALL", "--security-opt", "no-new-privileges",
        "--user", f"{os.getuid()}:{os.getgid()}",
        "--env", "HOME=/tmp", "--env", "PYTHONDONTWRITEBYTECODE=1",
        "-v", f"{code_path}:/workspace/script.py:ro",
        *_sandbox_mounts(),
        "--workdir", "/workspace",
        image,
        "python", "/workspace/script.py",
    ]
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        raise


@tool
def execute_python(
    code: Annotated[str, "Python code to execute."],
) -> Annotated[dict, "Execution result with output, error, and file_path fields."]:
    """Execute Python code and return the result.

    The code is written to a temporary file and run in the sandbox (or
    directly via subprocess, see module docstring). stdout and stderr
    are captured and returned.

    Data from previous agents is available at the per-session path given
    in the prompt (``data/outputs/<session>/cypher_results.json``); load it
    with ``json.load`` or ``pandas.read_json``.
    """
    mode = os.environ.get(SANDBOX_MODE_ENV, "docker")
    if mode not in ("docker", "subprocess"):
        # Fail loudly: a typo'd value must never silently select the
        # unsandboxed path (contract: no silent unsandboxed fallback).
        return {
            "output": "",
            "error": (
                f"Invalid {SANDBOX_MODE_ENV}={mode!r}; "
                "use 'docker' or 'subprocess'."
            ),
            "file_path": None,
        }

    # Write script to a unique temp file to avoid race conditions
    fd, code_path = tempfile.mkstemp(suffix=".py", prefix="grass_agent_")
    try:
        os.close(fd)
        with open(code_path, "w", encoding="utf-8") as f:
            f.write(code)

        if mode == "docker":
            result = _run_sandboxed(code_path)
        else:
            result = subprocess.run(
                [sys.executable, code_path],
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
                cwd=os.path.dirname(DATA_DIR),  # project root
            )

        stdout = result.stdout[:MAX_OUTPUT_CHARS] if result.stdout else ""
        stderr = result.stderr[:MAX_OUTPUT_CHARS] if result.stderr else ""

        # 125 = docker itself failed (typically the sandbox image is not
        # built) rather than the script erroring — surface an ops hint.
        if mode == "docker" and result.returncode == 125:
            stderr += (
                "\n[sandbox] docker run failed — is the sandbox image built? "
                "Run: docker build -t grass-sandbox docker/sandbox"
            )

        # A killed container (e.g. 137 = OOM) can exit non-zero with empty
        # stderr; error must be non-empty or callers would read it as success.
        if result.returncode != 0 and not stderr:
            stderr = f"Process exited with code {result.returncode}"

        if result.returncode == 0:
            return {
                "output": stdout,
                "error": None,
                "file_path": code_path,
            }
        else:
            return {
                "output": stdout,
                "error": stderr,
                "file_path": code_path,
            }

    except subprocess.TimeoutExpired:
        return {
            "output": "",
            "error": f"Execution timed out after {TIMEOUT_SECONDS}s",
            "file_path": code_path,
        }
    except OSError as e:
        # docker CLI missing / daemon socket inaccessible — an ops
        # problem, not a script problem; a raw FileNotFoundError would
        # send the model off "fixing" its own code.
        return {
            "output": "",
            "error": (
                f"Sandbox unavailable ({e}). Is Docker installed and the "
                "image built? Run: docker build -t grass-sandbox docker/sandbox"
            ),
            "file_path": code_path,
        }
    except Exception as e:
        return {
            "output": "",
            "error": str(e),
            "file_path": code_path,
        }
