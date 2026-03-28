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

## Architecture

The first skill-hub modules should be:

- `SkillCatalog`
- `HubProvider`
- `SkillInstaller`
- `SkillLockfile`
- `SkillTrust`

That gives the OS a clean skill supply-chain boundary.

The harness then consumes only installed local skills.
