# Chapter 45: Skill Hubs, Trust, and Installation

Local skills are already part of the harness.

But a real Agent OS also needs a supply-chain boundary for remote skills.

That means the OS should be able to:

- search remote skill hubs
- install skills into a chosen scope
- remember what was installed and from where
- keep the harness focused on using already-installed local skills

This chapter implements the first real slice of that system.

## The Core Boundary

The harness should:

- discover local installed skills
- render skill prompt sections
- let agents use those skills

The Agent OS should:

- talk to a remote hub or hub bridge
- install skills into local directories
- keep an install record
- expose that state to the work console and later to operators

This boundary matters because remote skills are supply-chain inputs.

The harness should never silently fetch arbitrary remote code or instructions by itself.

## What We Implement in the First Slice

We keep the first implementation small and practical:

- a `ClawHubClient` bridge
- a file-backed `SkillHubInstallStore`
- a `SkillHubManager`
- work-console commands for:
  - `/skills`
  - `/skill search <query>`
  - `/skill install <slug> [--user] [--version <v>] [--force]`

The implementation lives in:

- [`skill_hubs.py`](/Users/dzung/mini-claw-code/mini-claw-code-py/src/mini_claw_code_py/os/skill_hubs.py)

## Why We Use a CLI Bridge First

The official ClawHub documentation already exposes a stable CLI workflow for:

- `clawhub search "query"`
- `clawhub install <slug>`
- `--workdir`
- `--dir`
- `--version`
- `--force`

For this tutorial, bridging through that CLI is a good first production shape because:

- it keeps the Python code flat
- it avoids building a custom registry HTTP client too early
- it preserves the OS boundary cleanly
- later chapters can replace or extend the client without changing the work-console commands

The implementation prefers:

- `clawhub`

and falls back to:

- `npx -y clawhub`

if the dedicated CLI is not installed.

## Scope

The first slice supports two installation scopes:

- project scope
- user scope

Those map naturally to the local skill roots already used by the harness:

- project: `<cwd>/.agents/skills`
- user: `~/.agents/skills`

That means a newly installed skill can become available to future turns without inventing a second skill-loading system.

## Architecture

### `ClawHubClient`

This class is a thin bridge around the external CLI.

It supports:

- `search(query, limit=...)`
- `install(slug, workdir=..., install_dir=..., version=..., force=...)`

The return value is a small command-result object:

- argv
- cwd
- exit code
- stdout
- stderr

This is important because it makes the bridge:

- traceable
- testable
- easy to audit later

### `SkillHubInstallStore`

The Agent OS also needs durable install metadata.

That store records:

- provider
- slug
- scope
- workdir
- install directory
- requested version
- installed time
- updated time
- command prefix

The first file lives in the OS state root:

- `.mini-claw/os/skill_hub_installs.json`

### `SkillHubManager`

This is the work-side service that connects the two ideas:

- remote hub bridge
- local skill discovery

It provides:

- `search(...)`
- `install_project_skill(...)`
- `install_user_skill(...)`
- `render()`

So the work console can ask one service for:

- local installed skills
- hub install history
- search results
- install actions

## Why This Design Is Good

This chapter intentionally does **not** try to solve everything at once.

It does not yet build:

- trust approvals
- signed manifests
- team-scoped skill assignment
- update/remove/disable flows
- operator moderation
- raw registry API clients

But it does establish the right production boundary:

- one OS module owns hub interactions
- one store owns install metadata
- the harness keeps using local skills only

That is the correct backbone for later trust and policy chapters.

## Runtime Flow

The first runtime path looks like this:

```text
work console
  -> /skill search "calendar"
  -> SkillHubManager.search(...)
  -> ClawHubClient.search(...)
  -> external clawhub CLI
  -> raw output shown to user
```

Installation looks like this:

```text
work console
  -> /skill install calendar-helper
  -> SkillHubManager.install_project_skill(...)
  -> ClawHubClient.install(...)
  -> external clawhub CLI installs into .agents/skills
  -> SkillHubInstallStore.upsert(...)
  -> later turns discover the new local skill
```

That last step is important:

- the work console does not need to reinvent skill loading
- the harness already knows how to discover local skills

## Why the Next Turn Can Use the New Skill

This project already rebuilds hosted agents through the factory and config path.

That means after installing into:

- `.agents/skills`

the next fresh harness runtime can discover the new skill through the existing `SkillRegistry`.

So the remote install path integrates naturally into the current architecture.

## Work Console Surface

This chapter adds the first real user-facing hub commands:

### `/skills`

Shows:

- local skills discovered in the current scopes
- tracked hub installs from the OS store

### `/skill search <query>`

Runs the hub bridge and shows raw search output.

This is a deliberate first-step choice:

- we do not depend on a custom JSON search API yet
- we can still keep the result useful in a terminal workflow

### `/skill install <slug> [--user] [--version <v>] [--force]`

Installs a remote skill into:

- project scope by default
- user scope when `--user` is used

The first slice also supports:

- `/skill install-user <slug> ...`

as an explicit user-scope shortcut.

## Trust and Safety

Even in this first slice, the design still treats remote skills as special:

- install goes through an explicit command
- install actions are recorded in the OS state
- the harness itself is still local-skill only

What we do **not** do yet:

- silent auto-install during a model turn
- direct remote skill execution
- hidden background updates

That is important.

Skill hubs are powerful, but they should remain visible and auditable.

## Testing Focus

The Chapter 45 tests cover:

1. command selection for `clawhub` vs `npx -y clawhub`
2. exact CLI argument construction
3. project vs user install scope
4. file-backed install metadata
5. rendering local skills together with hub install history
6. work-console command handling for `/skills` and `/skill search`

Tests live in:

- [`test_ch45.py`](/Users/dzung/mini-claw-code/mini-claw-code-py/tests/test_ch45.py)
- [`test_tui.py`](/Users/dzung/mini-claw-code/mini-claw-code-py/tests/test_tui.py)

## What Still Comes Later

This chapter is the backbone, not the end state.

The next realistic improvements are:

- trust approvals before install
- update and remove commands
- team-level skill assignment
- lockfile/version pinning improvements
- richer structured search results
- operator-side audit and moderation surfaces

But after this chapter, the Agent OS already has a real remote-skill entry point:

- search remote
- install locally
- trace what happened
- keep the harness local-first
