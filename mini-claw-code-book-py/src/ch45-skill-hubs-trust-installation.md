# Chapter 45: Skill Hubs, Trust, and Installation

Local skills are already part of the harness.

But a real Agent OS should also support remote skill discovery and installation.

That is where skill hubs come in.

## The Core Distinction

The harness should:

- load installed local skills
- render skill prompt sections
- let agents use those skills

The Agent OS should:

- search remote hubs
- inspect remote skill metadata
- review or scan skills
- install and pin skills
- manage trust state
- decide which agents or teams may use which installed skills

That boundary is important.

Remote skills are supply-chain inputs.

They should not be silently installed and executed by the harness.

## Requirements

The first skill-hub layer should support:

- search
- inspect
- install
- pin
- update
- disable
- remove

And it should require explicit approval for installation.

It should also support scope decisions such as:

- user-wide skill
- project skill
- agent-specific enablement
- team-specific enablement

## Architecture

The first skill-hub modules should be:

- `SkillCatalog`
- `HubProvider`
- `SkillInstaller`
- `SkillLockfile`
- `SkillTrust`

And later likely:

- `SkillPolicy`
- `SkillAssignments`
- install audit history

That gives the OS a clean skill supply-chain boundary.

The harness then consumes only installed local skills.

Remote skill install flows should also be fully traceable:

- who searched
- who approved
- what version was installed
- where it was assigned
