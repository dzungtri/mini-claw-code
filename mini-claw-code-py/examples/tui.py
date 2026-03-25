from __future__ import annotations

import asyncio

from mini_claw_code_py import (
    AgentDone,
    AgentError,
    AgentTextDelta,
    AgentToolCall,
    AskTool,
    BashTool,
    ChannelInputHandler,
    EditTool,
    Message,
    OpenRouterProvider,
    PlanAgent,
    ReadTool,
    UserInputRequest,
    WriteTool,
)


async def ui_event_loop(
    queue: "asyncio.Queue[object]",
    input_queue: "asyncio.Queue[UserInputRequest]",
) -> None:
    while True:
        agent_task = asyncio.create_task(queue.get())
        input_task = asyncio.create_task(input_queue.get())
        done, pending = await asyncio.wait(
            [agent_task, input_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        events = [task.result() for task in done]
        events.sort(key=lambda event: 0 if isinstance(event, UserInputRequest) else 1)

        for event in events:
            if isinstance(event, UserInputRequest):
                print()
                print(f"  {event.question}")
                for index, option in enumerate(event.options, start=1):
                    print(f"    {index}) {option}")
                answer = input("  > ").strip()
                if answer.isdigit():
                    number = int(answer)
                    if 1 <= number <= len(event.options):
                        answer = event.options[number - 1]
                event.response_future.set_result(answer)
                continue

            if isinstance(event, AgentTextDelta):
                print(event.text, end="", flush=True)
            elif isinstance(event, AgentToolCall):
                print(f"\n{event.summary}")
            elif isinstance(event, AgentDone):
                print("\n")
                return
            elif isinstance(event, AgentError):
                print(f"\nerror: {event.error}\n")
                return


async def main() -> None:
    provider = OpenRouterProvider.from_env()
    input_queue: asyncio.Queue[UserInputRequest] = asyncio.Queue()
    event_queue: asyncio.Queue[object] = asyncio.Queue()
    agent = (
        PlanAgent(provider)
        .tool(BashTool())
        .tool(ReadTool())
        .tool(WriteTool())
        .tool(EditTool())
        .tool(AskTool(ChannelInputHandler(input_queue)))
    )

    history: list[Message] = []
    plan_mode = False

    while True:
        prefix = "[plan] > " if plan_mode else "> "
        try:
            prompt = input(prefix).strip()
        except EOFError:
            print()
            return

        if not prompt:
            continue
        if prompt == "/plan":
            plan_mode = not plan_mode
            state = "ON" if plan_mode else "OFF"
            print(f"plan mode {state}\n")
            continue

        history.append(Message.user(prompt))
        if plan_mode:
            worker = asyncio.create_task(agent.plan(history, event_queue))
            await ui_event_loop(event_queue, input_queue)
            plan_text = await worker
            approval = input("Accept this plan? [y/n/feedback] ").strip()
            if approval.lower() == "y":
                event_queue = asyncio.Queue()
                history.append(Message.user("Proceed with the approved plan."))
                worker = asyncio.create_task(agent.execute(history, event_queue))
                await ui_event_loop(event_queue, input_queue)
                await worker
            elif approval.lower() not in {"n", "no"}:
                history.append(Message.user(f"Revise the plan with this feedback: {approval}"))
            else:
                print(f"Plan rejected:\n{plan_text}\n")
        else:
            worker = asyncio.create_task(agent.execute(history, event_queue))
            await ui_event_loop(event_queue, input_queue)
            await worker


if __name__ == "__main__":
    asyncio.run(main())
