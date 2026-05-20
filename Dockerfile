# syntax=docker/dockerfile:1
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
#
# Container image for the nexus-core public deployment (nexusmcp.site).
# Builds the HTTP API + MCP-over-HTTP server; runs as a non-root user and
# listens on $PORT (Cloud Run injects this; defaults to 8080).

FROM python:3.12-slim

# Unbuffered stdout/stderr so logs surface promptly in Cloud Logging.
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

# Non-root runtime user.
RUN useradd --create-home --uid 10001 nexus

WORKDIR /app

# Install dependencies. Only the files the build needs are copied, so a code
# change does not invalidate the dependency layer.
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY src/ ./src/
RUN pip install ".[serve]"

USER nexus
EXPOSE 8080

# The CLI reads HOST/PORT from the environment; Cloud Run supplies PORT.
CMD ["nexus-core", "serve"]
