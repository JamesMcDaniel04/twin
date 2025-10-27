"""Command line entry for TwinOps."""

from __future__ import annotations

import asyncio

import uvicorn

from backend.api.main import app


def run_server() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8080)


def main() -> None:
    run_server()


if __name__ == "__main__":
    main()
