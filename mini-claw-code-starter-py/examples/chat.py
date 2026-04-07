from __future__ import annotations

import asyncio


async def main() -> None:
    raise NotImplementedError(
        "Create a provider, build an agent with all four tools, keep a history list, "
        "read prompts from stdin, and call agent.chat() in a loop"
    )


if __name__ == "__main__":
    asyncio.run(main())
