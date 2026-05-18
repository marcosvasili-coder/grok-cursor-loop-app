# Project
Single-file Python desktop app (Tkinter GUI + pystray menu bar) that watches `plans/handoffs/` for `feedback-*.md` files and drives the Grok web UI through Playwright — uploading each file, sending a PM prompt, capturing downloads, and pausing on safety phrases. macOS-first; not a CLI tool, not a Grok API client, and not cross-platform-tested.

# Stack
- Python 3.10+ (current venv uses 3.14; macOS Python with bundled Tcl/Tk required for Tkinter)
- Playwright sync API + Chromium (`playwright>=1.40.0`)
- Tkinter (stdlib) for the GUI; pystray + Pillow for the menu bar icon
- watchdog (`>=4.0.0`) for filesystem events on `plans/handoffs/`
- macOS shell-outs: `osascript` (notifications), `afplay` (sound)
- `urllib` to POST ntfy.sh push notifications

# Commands
- install: `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && playwright install chromium`
- dev / run: `source .venv/bin/activate && python3 grok_loop_app.py`
- test: `python3 scripts/smoke_check.py` (imports + folder creation; no network, no Grok login)
- lint: `python3 -m py_compile grok_loop_app.py scripts/smoke_check.py` (no flake8/ruff/black configured)
- build: n/a — runs from source
- clean session: `rm .playwright/grok_storage.json` then re-run app to re-login

# Structure
- `grok_loop_app.py` — entire app: SELECTORS, AppConfig dataclass, FeedbackHandler (watchdog), GrokAutomation (Playwright worker), LoopController (queues + threads), GrokLoopApp (Tk UI)
- `scripts/smoke_check.py` — pre-flight import + directory check
- `requirements.txt` — runtime deps (no dev/test deps)
- `plans/handoffs/` — drop `feedback-*.md` here (only matching prefix is queued)
- `plans/grok-pm-specs/` — downloaded artefacts, timestamp-prefixed (gitignored)
- `plans/debug/screenshots/` — failure screenshots when "Save screenshot on failure" is on (gitignored)
- `secrets/` — `README.md` + `example.env` tracked; everything else gitignored
- `.playwright/grok_storage.json` — Playwright `storage_state` for Grok login (gitignored)
- `.grok_loop_state.json` — persisted `AppConfig` (gitignored)
- `.cursor/` — Cursor agent rules + `chat-path-migration.md` (repo lives on `/Volumes/External SSD/dev/...`, not `~`)
- `.claude/` — this Claude Code config + skills

# Rules
- Never edit without explicit confirmation: `.playwright/grok_storage.json` (live session), `.grok_loop_state.json` (persisted config — app rewrites it), `secrets/local.env`, anything else under `secrets/` except `README.md` / `example.env`, and `requirements.txt` (treat as the dep lock for this repo).
- Never commit secrets, cookies, or `__pycache__/`. Verify `.gitignore` covers anything new under `secrets/`, `.playwright/`, `plans/grok-pm-specs/`, `plans/debug/`.
- Always run `python3 scripts/smoke_check.py` before committing changes that touch imports or directory layout.
- Playwright work happens **only on the automation worker thread** (`LoopController._worker_main`). UI updates from the worker must go through `controller.post_ui(...)` / `root.after(0, ...)` — never call Tk widgets directly from background threads.
- Cross-thread signalling uses `queue.Queue` + `threading.Event` (`stop_event`). Do not introduce locks or shared mutables without going through these primitives.
- Catch specific exceptions (`OSError`, `json.JSONDecodeError`, `tk.TclError`, `PlaywrightTimeoutError`); avoid bare `except:`. Subprocess calls take `timeout=` and `check=False`.
- Tune Grok UI behaviour through `SELECTORS` (top of `grok_loop_app.py`) or an external `grok_selectors.json` — do not hardcode new CSS selectors deep in methods.
- Wrap optional third-party imports (`PIL`, `pystray`, `playwright`, `watchdog`) in try/except so `smoke_check` and `--help`-style runs degrade gracefully.
- Treat the app as macOS-only at runtime: gate `osascript`/`afplay` on `sys.platform == "darwin"`.

# Patterns
- See `grok_loop_app.py:264-294` for the `AppConfig` dataclass + `to_json` / `from_json` round-trip pattern (used for all persisted settings).
- See `grok_loop_app.py:418-451` for the watchdog `FeedbackHandler` shape — name-prefix filter, dedupe via `_seen` set under a lock, hand off via `enqueue` callback.
- See `grok_loop_app.py:477-828` for the `GrokAutomation` worker class — stop-event checks, Playwright lifecycle (`_launch` / `close` / `kill_hard`), login-wall detection, selector iteration.
- See `grok_loop_app.py:835-1141` for `LoopController` cross-thread plumbing — `cmd_queue`, `ui_queue`, `handoff_queue`, `post_ui`, periodic `root.after` polling.
- See `scripts/smoke_check.py` for the standalone-script style: `pathlib`, no argparse for tiny utilities, exit code via `sys.exit(main())`.

# Imports
@CLAUDE.local.md

# Self-Maintenance
When you discover something that would have helped you work in this repo better — a pattern, a gotcha, a convention — add it to CLAUDE.md under the relevant section. One line where possible. If CLAUDE.md grows beyond 200 lines, move content to `.claude/skills/` instead.

# Git workflow

- **Integration branch:** use the repo default (usually `main`) as the source of truth; merge finished work there.
- **Feature branches:** short-lived, one purpose each; prefer clear names (`feat/…`, `fix/…`).
- **After merge:** `git checkout <default>` && `git pull`, then delete the finished feature branch (and remote tracking branch when applicable).
- **Sync:** prefer `git pull --rebase` while on a feature branch before opening or updating a PR (optional: `git config pull.rebase true`).
- **Agents / automation:** do not leave the checkout on incidental `cursor/…` or unnamed branches without intent; return to the integration branch when a task is complete unless explicitly continuing feature work.

<!-- setup-ai-context-git-workflow v1 -->

## Claude Insights Applied — 2026-05-18

- Before starting work, verify current repo/directory matches handoff context — if a handoff prompt references a different project, STOP and ask.
- Before suggesting next steps, check `git log` and merged PRs first — the work may already be shipped.
- After logic changes on a branch shared with Cursor, commit immediately. Treat uncommitted work on Cursor-shared branches as ephemeral.
- For long outputs (audits, reviews, analyses): write to a markdown file, return summary + path rather than inlining in chat.
- UI/UX reviews: default to a full screenshot walkthrough of all affected screens — not just the active change.
- Before any multi-step or autonomous task, output a PREFLIGHT block: current dir + expected repo, current branch, clean working tree?, work already shipped that overlaps?, blockers. Stop if anything is off.
