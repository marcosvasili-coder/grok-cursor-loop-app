---
name: resume
description: Reconstruct full session context from git state, roadmap, and memory in one command — verify repo/branch before any execution.
---

## When to use
At the start of any session, especially after a context gap or handoff.

## Steps
1. Print current directory and confirm it matches the expected repo
2. Run `git log --oneline -20` and `git status`
3. Run `gh pr list --state open` (if gh is available)
4. Check for uncommitted work on all worktrees (`git worktree list`)
5. Read `.claude/handoff.md` if it exists
6. Read `MEMORY.md` or `.claude/MEMORY.md` if either exists
7. Summarise what was likely in-flight and propose the 3 highest-priority next actions

## Guard
If the current directory does not match what the handoff describes — STOP and ask before doing anything.
