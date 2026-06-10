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

# Install dependencies from the hash-pinned lock first (reproducible builds +
# supply-chain verification — `--require-hashes` refuses any package whose
# artifact hash isn't in the lock), then the package itself without re-resolving
# its deps. Only the files the build needs are copied, so a code change does not
# invalidate the dependency layer.
#
# Regenerate the lock after a dependency change in pyproject.toml:
#   uv pip compile pyproject.toml --extra serve --generate-hashes \
#     -o requirements-serve.lock
COPY pyproject.toml README.md LICENSE NOTICE requirements-serve.lock ./
COPY src/ ./src/
RUN pip install --require-hashes --no-deps -r requirements-serve.lock \
 && pip install --no-deps .

USER nexus
EXPOSE 8080

# The CLI reads HOST/PORT from the environment; Cloud Run supplies PORT.
CMD ["nexus-core", "serve"]
