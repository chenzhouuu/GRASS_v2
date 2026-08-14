"""Python code execution tool for GRASS agents.

Writes code to a file and executes it via subprocess, capturing
stdout and stderr.  Data from previous agents (e.g. cypher_results)
is persisted to a per-session JSON file (``data/outputs/<session>/
cypher_results.json``) so that executed code can load it with
``pd.read_json`` or ``json.load``; agents inject the concrete path
into their prompts. Without a session id the legacy shared path
``data/cypher_results.json`` is used (benchmarks, tests).
"""

import json
import os
import re
import subprocess
import tempfile
from typing import Annotated, Optional

from langchain_core.tools import tool

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
)
os.makedirs(DATA_DIR, exist_ok=True)

PROJECT_ROOT = os.path.dirname(DATA_DIR)

TIMEOUT_SECONDS = 120
MAX_OUTPUT_CHARS = 30_000


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


def persist_cypher_results(
    records: list[dict], session_id: Optional[str] = None
) -> str:
    """Write cypher_results to the session's JSON file.

    Returns the project-root-relative path to the written file (the same
    string agents inject into prompts).
    """
    rel_path = cypher_results_path(session_id)
    abs_path = os.path.join(PROJECT_ROOT, rel_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, default=str)
    return rel_path


@tool
def execute_python(
    code: Annotated[str, "Python code to execute."],
) -> Annotated[dict, "Execution result with output, error, and file_path fields."]:
    """Execute Python code and return the result.

    The code is written to a temporary file and run as a subprocess.
    stdout and stderr are captured and returned.

    Data from previous agents is available at the per-session path given
    in the prompt (``data/outputs/<session>/cypher_results.json``); load it
    with ``json.load`` or ``pandas.read_json``.
    """
    # Write script to a unique temp file to avoid race conditions
    fd, code_path = tempfile.mkstemp(suffix=".py", prefix="grass_agent_")
    try:
        os.close(fd)
        with open(code_path, "w", encoding="utf-8") as f:
            f.write(code)

        result = subprocess.run(
            ["python", code_path],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            cwd=os.path.dirname(DATA_DIR),  # project root
        )

        stdout = result.stdout[:MAX_OUTPUT_CHARS] if result.stdout else ""
        stderr = result.stderr[:MAX_OUTPUT_CHARS] if result.stderr else ""

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
    except Exception as e:
        return {
            "output": "",
            "error": str(e),
            "file_path": code_path,
        }
