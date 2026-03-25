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
    SkillRegistry,
    SYSTEM_PROMPT_FILE_ENV,
    SimpleAgent,
    WriteTool,
    load_prompt_template,
    render_system_prompt,
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
    prompt_template = load_prompt_template(
        SYSTEM_PROMPT_FILE_ENV,
        DEFAULT_SYSTEM_PROMPT_TEMPLATE,
    )
    skills_section = SkillRegistry.discover_default(Path.cwd()).prompt_section()
    system_prompt = render_system_prompt(
        prompt_template,
        cwd=cwd,
        extra_sections=[skills_section],
    )
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
