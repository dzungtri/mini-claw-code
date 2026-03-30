from __future__ import annotations

import asyncio

from ..os.telegram import run_telegram_runtime_from_args


def main() -> None:
    asyncio.run(run_telegram_runtime_from_args())


if __name__ == "__main__":
    main()
