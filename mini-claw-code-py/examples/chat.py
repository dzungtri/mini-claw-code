from __future__ import annotations

import asyncio
from pathlib import Path

from mini_claw_code_py import (
    AskTool,
    BashTool,
    CliInputHandler,
    DEFAULT_SYSTEM_PROMPT_TEMPLATE,
    EditTool,
    Message,
    OpenRouterProvider,
    ReadTool,
    SYSTEM_PROMPT_FILE_ENV,
    SimpleAgent,
    WriteTool,
    load_prompt_template,
)


async def main() -> None:
    provider = OpenRouterProvider.from_env()
    agent = (
        SimpleAgent(provider)
        .tool(BashTool())
        .tool(ReadTool())
        .tool(WriteTool())
        .tool(EditTool())
        .tool(AskTool(CliInputHandler()))
    )

    cwd = str(Path.cwd())
    system_prompt = load_prompt_template(
        SYSTEM_PROMPT_FILE_ENV,
        DEFAULT_SYSTEM_PROMPT_TEMPLATE,
    ).replace("{{cwd}}", cwd)
    history = [Message.system(system_prompt)]

    while True:
        try:
            prompt = input("> ").strip()
        except EOFError:
            print()
            return

        if not prompt:
            continue

        history.append(Message.user(prompt))
        print("    thinking...", end="", flush=True)
        try:
            text = await agent.chat(history)
            print("\r\x1b[2K" + text.strip() + "\n")
        except Exception as exc:
            print(f"\r\x1b[2Kerror: {exc}\n")


if __name__ == "__main__":
    asyncio.run(main())
