# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Command-line entrypoint for nexus-core.

Exposes two run modes:

- ``nexus-core serve`` — the public HTTP API (with the MCP transport mounted),
  the entrypoint used by the container image and the nexusmcp.site deployment.
- ``nexus-core mcp`` — the MCP server over stdio, for local clients such as
  Claude Desktop.
"""

from __future__ import annotations

import argparse
import os

import uvicorn

from . import __version__
from .app import build_market_provider, create_app
from .data.macro import FredMacroData
from .engine.regime import RegimeEngine
from .mcp.server import build_server


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to a run mode. Returns a process exit code."""
    parser = argparse.ArgumentParser(
        prog="nexus-core",
        description="Open regime-adaptive financial analysis engine.",
    )
    parser.add_argument(
        "--version", action="version", version=f"nexus-core {__version__}"
    )
    subparsers = parser.add_subparsers(dest="command")

    serve_parser = subparsers.add_parser(
        "serve", help="Run the public HTTP API + MCP-over-HTTP server"
    )
    serve_parser.add_argument(
        "--host", default=os.environ.get("HOST", "0.0.0.0"), help="Bind address"
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", "8080")),
        help="Bind port (Cloud Run supplies PORT)",
    )

    subparsers.add_parser(
        "mcp", help="Run the MCP server over stdio (for Claude Desktop)"
    )

    subparsers.add_parser(
        "snapshot", help="Run the daily benchmark-price snapshot job (Cloud Run Job)"
    )

    args = parser.parse_args(argv)

    if args.command == "serve":
        _serve_http(args.host, args.port)
        return 0
    if args.command == "mcp":
        _serve_mcp_stdio()
        return 0
    if args.command == "snapshot":
        from .jobs.daily_snapshot import run as run_snapshot_job

        return run_snapshot_job()

    parser.print_help()
    return 1


def _serve_http(host: str, port: int) -> None:
    uvicorn.run(create_app(), host=host, port=port)


def _serve_mcp_stdio() -> None:
    engine = RegimeEngine(
        market_data=build_market_provider(),
        macro_data=FredMacroData(),
    )
    build_server(name="nexus-core", regime_engine=engine).run()


if __name__ == "__main__":
    raise SystemExit(main())
