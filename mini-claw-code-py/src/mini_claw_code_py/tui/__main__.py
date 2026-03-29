from __future__ import annotations

import asyncio

from .app import run_cli


if __name__ == "__main__":
    asyncio.run(run_cli())
