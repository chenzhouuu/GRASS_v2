# Sandbox image for agent-generated Python code (Analytics, Optimization,
# Report, ScenarioRunner). Build from the project root:
#
#   docker build -t grass-sandbox docker/sandbox
#
# Executions run with --network=none and a read-only root filesystem, so every
# library the generated code may need must be baked in here (pulp bundles the
# CBC solver binary in its wheel).
FROM python:3.11-slim

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Non-root default user; execute_python additionally passes --user <host uid>
# so files written to the mounted data dir stay owned by the host user.
RUN useradd --create-home --uid 1000 sandbox
USER sandbox
WORKDIR /workspace
