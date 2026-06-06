"""Python code execution tool for GRASS agents.

Writes code to a file and executes it via subprocess, capturing
stdout and stderr.  Data from previous agents (e.g. cypher_results)
is persisted to ``data/cypher_results.json`` so that executed code
can load it with ``pd.read_json`` or ``json.load``.
"""

import json
import os
import subprocess
import tempfile
from typing import Annotated

from langchain_core.tools import tool

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
)
os.makedirs(DATA_DIR, exist_ok=True)

TIMEOUT_SECONDS = 120
MAX_OUTPUT_CHARS = 30_000


def persist_cypher_results(records: list[dict]) -> str:
    """Write cypher_results to a JSON file so executed code can load it.

    Returns the absolute path to the written file.
    """
    path = os.path.join(DATA_DIR, "cypher_results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, default=str)
    return path


@tool
def execute_python(
    code: Annotated[str, "Python code to execute."],
) -> Annotated[dict, "Execution result with output, error, and file_path fields."]:
    """Execute Python code and return the result.

    The code is written to a temporary file and run as a subprocess.
    stdout and stderr are captured and returned.

    Data from previous agents is available at ``data/cypher_results.json``.
    Use ``import json; data = json.load(open('data/cypher_results.json'))``
    or ``pandas.read_json('data/cypher_results.json')`` to load it.
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
