---
name: python-packaging
description: Help with Python packaging, version bumps, release preparation, and publishing workflows for projects that use pyproject.toml or uv.
compatibility: Works best in repositories that use pyproject.toml and uv.
metadata:
  category: python
---

# Python Packaging

Use this skill when the user asks about:

- version bumps
- release preparation
- package publishing
- `pyproject.toml`
- `uv build`
- wheel or source distribution problems

## Workflow

1. Read `pyproject.toml` before suggesting packaging changes.
2. Look for the package name, current version, build backend, and publish-related metadata.
3. If the task is a release, read `references/release-checklist.md`.
4. Prefer `uv` commands when the repository already uses `uv`.
5. If a publish step is risky, explain the command before running it.

## Output style

- Be concrete about changed files and commands.
- Mention version numbers explicitly.
- Keep packaging advice tied to the current repository instead of giving generic Python advice.
