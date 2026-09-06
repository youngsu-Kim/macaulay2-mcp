FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    HOME=/root \
    PATH=/root/.local/bin:/root/.opencode/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# Macaulay2 1.26 (latest stable) from the official PPA
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg software-properties-common \
    && add-apt-repository -y ppa:macaulay2/macaulay2 \
    && apt-get update \
    && apt-get install -y --no-install-recommends macaulay2 \
    && rm -rf /var/lib/apt/lists/* \
    && M2 --version

# uv (Python toolchain; the MCP server runs from this repo's source)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# opencode CLI
RUN curl -fsSL https://opencode.ai/install | bash

# The MCP server from this repository
COPY . /workspace/m2-mcp
RUN cd /workspace/m2-mcp && uv sync --frozen \
    && uv run macaulay2-mcp selftest

# E2E harness files
COPY e2e/opencode.json /workspace/opencode.json
COPY e2e/task.txt /workspace/task.txt
COPY e2e/assert.py /workspace/assert.py

WORKDIR /workspace
CMD ["bash"]
