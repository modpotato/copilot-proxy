"""Command-line interface for running the Copilot proxy."""
from __future__ import annotations

import argparse
from typing import Optional

import uvicorn

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 11434


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Copilot GLM proxy server.")
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Host interface to bind (default: {DEFAULT_HOST}).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port to bind (default: {DEFAULT_PORT}).",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload (useful for development).",
    )
    parser.add_argument(
        "--log-level",
        default="info",
        help="Log level passed to Uvicorn (default: info).",
    )
    parser.add_argument(
        "--proxy-app",
        default="copilot_proxy.app:app",
        help=(
            "Dotted path to the FastAPI application passed to Uvicorn "
            "(default: copilot_proxy.app:app)."
        ),
    )
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    uvicorn.run(
        args.proxy_app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
