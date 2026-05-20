---
name: git
description: Solo developer hybrid git workflow — branch when it matters, commit direct when it doesn't
---

# Git Skill

## When to use
Any task involving commits, branches, merges, pushes, or releases.

## Branching policy
Decide first: does this change carry risk?

**Commit direct to `main`** for: typos, comment fixes, version bumps,
config tweaks, documentation, single-line obvious fixes.

**Branch first** for: new features, bug fixes with logic changes,
refactors, multi-file changes, anything that could break the build.

## Branch naming
- `feat/short-description`
- `fix/short-description`
- `refactor/short-description`
- `chore/short-description`
- `docs/short-description`
Kebab-case, under 40 chars.

## Commit messages — conventional commits, mandatory
- `feat: add X`
- `fix: prevent Y when Z`
- `refactor: extract X from Y`
- `chore: bump dependency X`
- `docs: clarify X`
- `test: cover X case`
- `ci: fix workflow Y`

Imperative mood. Subject under 72 chars. One concept per commit.
Body only when there's a real "why" worth recording.

## Merging
Squash merge feature branches into `main`. Final squashed commit uses
conventional commit format. After merge: delete local and remote branch.

## Pushing
- Push only after local tests pass
- Never `git push --force` — use `--force-with-lease` if needed
- Never rewrite history already on `main`
- Never force-push to `main` under any circumstance

## Releases
- Build from `main` only
- Annotated tags only: `git tag -a v1.2.3 -m "release notes"`
- Semver strict
- Builds always come from a tagged commit

## Forbidden without explicit confirmation
- `git push --force` (use `--force-with-lease`)
- `git reset --hard` on `main`
- `git rebase` on any branch already pushed
- Deleting unmerged branches
- Modifying or recreating an existing tag
