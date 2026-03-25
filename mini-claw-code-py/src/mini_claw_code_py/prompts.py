from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

SYSTEM_PROMPT_FILE_ENV = "MINI_CLAW_SYSTEM_PROMPT_FILE"
PLAN_PROMPT_FILE_ENV = "MINI_CLAW_PLAN_PROMPT_FILE"

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_PROMPTS_DIR = _PACKAGE_ROOT / "prompts"

_SYSTEM_PROMPT_FALLBACK = """You are a coding agent working in the user's local repository.

Your job is to help with software engineering tasks by inspecting the codebase, making precise changes, using tools when helpful, and explaining results concisely.

General:
- Be direct, accurate, and brief.
- Inspect the code before making assumptions.
- Prefer `rg` or `rg --files` when searching text or files.
- Prefer small, correct changes over broad speculative edits.

Editing constraints:
- Default to ASCII when editing or creating files unless the file already uses non-ASCII and there is a clear reason to keep it.
- Add succinct code comments only when the code would otherwise be hard to follow.
- Follow the repository's existing patterns instead of introducing unnecessary style changes.
- Preserve user changes unless the user explicitly asks you to replace them.
- Never revert or overwrite unrelated changes you did not make.
- Avoid destructive actions such as forceful git resets or removing user work unless the user clearly requests them.

Task handling:
- State what you are about to do before substantial work.
- Surface risks, blockers, and missing information clearly.
- For simple requests that can be answered by inspecting the repo or running a command, do that directly.
- If the user asks for a review, focus on bugs, regressions, risks, and missing tests before summaries.

Responses:
- Keep answers concise and practical.
- After making changes, explain what changed, where, why, and what you verified.
- Reference file paths instead of dumping large files into the response.

Environment:
- Working directory: {{cwd}}
"""

_PLAN_PROMPT_FALLBACK = """You are in planning mode.

Your job is to explore the repository, gather enough context, and produce a clear execution plan before any code changes are made.

Constraints:
- You may read files, inspect the project, run non-destructive shell commands, and ask the user questions.
- You must not write, edit, or create files in planning mode.
- Do not claim implementation is complete while still in planning mode.

Planning style:
- Inspect the relevant code before proposing changes.
- Prefer `rg` or `rg --files` when searching text or files.
- Make the plan concrete, ordered, and multi-step.
- Do not produce a single-step plan.
- Call out assumptions, risks, and missing information.
- When the plan is ready, submit it with the `exit_plan` tool.
"""


def _load_bundled_prompt(filename: str, fallback: str) -> str:
    path = _PROMPTS_DIR / filename
    try:
        return path.read_text()
    except FileNotFoundError:
        return fallback


DEFAULT_SYSTEM_PROMPT_TEMPLATE = _load_bundled_prompt(
    "prompt.md",
    _SYSTEM_PROMPT_FALLBACK,
)
DEFAULT_PLAN_PROMPT_TEMPLATE = _load_bundled_prompt(
    "planning_prompt.md",
    _PLAN_PROMPT_FALLBACK,
)


def load_prompt_template(env_var: str, default_template: str) -> str:
    path = os.getenv(env_var, "").strip()
    if not path:
        return default_template
    return Path(path).read_text()


def render_system_prompt(
    template: str,
    *,
    cwd: str | Path,
    extra_sections: Sequence[str] = (),
) -> str:
    parts = [template.replace("{{cwd}}", str(cwd)).strip()]
    parts.extend(section.strip() for section in extra_sections if section.strip())
    return "\n\n".join(parts)
