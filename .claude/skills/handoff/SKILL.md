---
name: handoff
description: Produce a session handoff summary — git state, open PRs, uncommitted work, and a copy-pasteable resume prompt for the next session.
---

## When to use
At the end of any session, or before switching to Cursor.

## Steps
1. Run `git status` and `git log --oneline -10`
2. Run `gh pr list --state open` (if gh is available)
3. Summarise uncommitted work and any stashed changes
4. List the 3 most likely next actions
5. Write a single copy-pasteable resume prompt to `.claude/handoff.md` (overwrite)
6. If `MEMORY.md` exists at repo root or `.claude/MEMORY.md`, update it with any new facts

## Output format
```
HANDOFF — read first, then continue.

Goal:
Non-goals / do not touch:
Branch:
Already done:
Commands already run:
Current state:
Next steps:
Open questions / risks:
```
