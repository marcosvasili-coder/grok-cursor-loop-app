# grok-cursor-loop-app

> Read `CLAUDE.md` for full project conventions before acting.

## Quick reference
- **Stack:** Python 3.10+ Tkinter + pystray desktop app driving Grok web UI via Playwright (macOS-first)
- **Integration branch:** `main`
- **Test:** `python3 scripts/smoke_check.py`
- **Lint/build:** `python3 -m py_compile grok_loop_app.py scripts/smoke_check.py` (no build step)
- **CI runner:** none detected

## Key files (read before acting)
- `CLAUDE.md` — must-read conventions and workflow
- `grok_loop_app.py` — entire app (SELECTORS, AppConfig, FeedbackHandler, GrokAutomation, LoopController, GrokLoopApp)
- `scripts/smoke_check.py` — pre-commit import + directory check
- `.claude/settings.json` — hooks: protected-file Write block, git-push guard, py_compile on edit, smoke_check on Stop
- `.cursor/rules/` — `git.mdc`, `git-workflow.mdc`, `cursor-agent-cli-workflow.mdc`, `self-improvement.mdc`

## Autonomy constraints
- Do not push, merge, or open PRs without explicit instruction
- Do not commit secrets or production credentials
- Never edit without explicit confirmation: `.playwright/grok_storage.json`, `.grok_loop_state.json`, `secrets/local.env`, `secrets/*.env`, `requirements.txt`, `grok_selectors.json` (Write hook will block)
- No `git push --force` without `--force-with-lease`; never force-push or `git reset --hard` on `main` (Bash hook will block)
- Playwright calls only on `LoopController._worker_main` thread; UI updates via `controller.post_ui(...)` / `root.after(0, ...)` — never touch Tk widgets from background threads
- Run `python3 scripts/smoke_check.py` before committing changes that touch imports or directory layout
- Do not hardcode CSS selectors deep in methods — extend `SELECTORS` at top of `grok_loop_app.py` or `grok_selectors.json`

<!-- repo-init-phase-7 v1 -->
