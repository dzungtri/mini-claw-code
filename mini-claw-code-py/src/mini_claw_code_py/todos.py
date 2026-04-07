from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .types import ToolDefinition


TODO_STATUSES = ("pending", "in_progress", "completed")


WRITE_TODOS_PROMPT_SECTION = """<todo_tracking>
You have an internal todo list tool: `write_todos`.

Use `write_todos` for non-trivial multi-step work to keep a short visible task list.

Best practices:
1. Keep the list short and concrete.
2. Mark exactly one task as `in_progress` when active work is underway.
3. Update the list when the plan changes or when a major step finishes.
4. Clear the list when the task is complete.

Preferred shape:
```json
{"items": [
  {"content": "Inspect the target files", "status": "completed"},
  {"content": "Edit the implementation", "status": "in_progress"},
  {"content": "Run the tests", "status": "pending"}
]}
```

Todo items are internal runtime state. They are shown to the user in the CLI for progress visibility.
</todo_tracking>"""


@dataclass(slots=True)
class TodoItem:
    content: str
    status: str = "pending"


class TodoBoard:
    def __init__(self) -> None:
        self._items: list[TodoItem] = []

    def replace(self, raw_items: Any) -> int:
        if raw_items is None:
            raise ValueError("missing required parameter: items")
        if not isinstance(raw_items, list):
            raise ValueError("items must be a list")

        items: list[TodoItem] = []
        for raw in raw_items:
            item = self._coerce_item(raw)
            if item is None:
                continue
            items.append(item)

        self._items = self._normalize_items(items)
        return len(self._items)

    def clear(self) -> None:
        self._items = []

    def items(self) -> list[TodoItem]:
        return list(self._items)

    def is_empty(self) -> bool:
        return not self._items

    def all_completed(self) -> bool:
        return bool(self._items) and all(item.status == "completed" for item in self._items)

    def complete_all(self) -> bool:
        if not self._items:
            return False
        changed = any(item.status != "completed" for item in self._items)
        self._items = [TodoItem(content=item.content, status="completed") for item in self._items]
        return changed

    def render(self) -> str:
        if not self._items:
            return "No active todos."
        lines = ["Todo list:"]
        for item in self._items:
            lines.append(f"- [{self._status_icon(item.status)}] {item.content}")
        return "\n".join(lines)

    def notice(self) -> str:
        return f"Todo list updated:\n{self.render()}"

    def status_summary(self) -> str:
        if not self._items:
            return "Todo list cleared."
        completed = sum(1 for item in self._items if item.status == "completed")
        active = next((item.content for item in self._items if item.status == "in_progress"), None)
        summary = f"Stored {len(self._items)} todo item(s)"
        if active is not None:
            summary += f"; active: {active}"
        if completed:
            summary += f"; completed: {completed}"
        return summary + "."

    @staticmethod
    def _coerce_item(raw: Any) -> TodoItem | None:
        if isinstance(raw, str):
            content, status = _split_inline_status(raw)
            if not content:
                return None
            return TodoItem(content=content, status=status)

        if not isinstance(raw, dict):
            raise ValueError("todo items must be strings or objects")

        content = raw.get("content")
        if not isinstance(content, str) or not content.strip():
            return None

        content, inline_status = _split_inline_status(content)
        status = raw.get("status", inline_status)
        if not isinstance(status, str):
            status = inline_status
        status = status.strip().lower()
        if status not in TODO_STATUSES:
            status = inline_status

        return TodoItem(content=content.strip(), status=status)

    @staticmethod
    def _normalize_items(items: list[TodoItem]) -> list[TodoItem]:
        normalized: list[TodoItem] = []
        seen: set[str] = set()
        in_progress_seen = False

        for item in items:
            key = item.content.casefold()
            if key in seen:
                continue
            seen.add(key)

            status = item.status
            if status == "in_progress":
                if in_progress_seen:
                    status = "pending"
                in_progress_seen = True
            normalized.append(TodoItem(content=item.content, status=status))

        return normalized

    @staticmethod
    def _status_icon(status: str) -> str:
        if status == "completed":
            return "x"
        if status == "in_progress":
            return ">"
        return " "


class WriteTodosTool:
    def __init__(self, board: TodoBoard) -> None:
        self._board = board
        self._definition = ToolDefinition.new(
            "write_todos",
            "Create or replace the internal todo list used to track plan and execution progress.",
        ).param_raw(
            "items",
            {
                "type": "array",
                "description": "The full replacement todo list.",
                "items": {
                    "oneOf": [
                        {"type": "string"},
                        {
                            "type": "object",
                            "properties": {
                                "content": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": list(TODO_STATUSES),
                                },
                            },
                            "required": ["content"],
                        },
                    ]
                },
            },
            True,
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def call(self, args: Any) -> str:
        if not isinstance(args, dict):
            raise ValueError("arguments must be an object")
        raw_items = args.get("items", args.get("todos"))
        self._board.replace(raw_items)
        return self._board.status_summary()


def render_todo_prompt_section() -> str:
    return WRITE_TODOS_PROMPT_SECTION


def _split_inline_status(text: str) -> tuple[str, str]:
    content = text.strip()
    status = "pending"
    patterns = {
        "in_progress": re.compile(r"\s*[\(\[]\s*in[_ -]?progress\s*[\)\]]\s*$", re.IGNORECASE),
        "completed": re.compile(r"\s*[\(\[]\s*completed\s*[\)\]]\s*$", re.IGNORECASE),
        "pending": re.compile(r"\s*[\(\[]\s*pending\s*[\)\]]\s*$", re.IGNORECASE),
    }
    for name, pattern in patterns.items():
        if pattern.search(content):
            content = pattern.sub("", content).strip()
            status = name
            break
    return content, status
