# macOS Integration Skill

## When to use
- You are adding a notification, sound, or push (ntfy) trigger.
- You hit "no module named `_tkinter`" or the GUI fails to render.
- You need to debug iCloud / Downloads file-lock issues during `read_file_retry`.
- You are adjusting environment-variable overrides for paths used by the app.

## Steps
1. Native notification: call `macos_notify(title, message)` (`grok_loop_app.py:313-330`). It runs `osascript -e 'display notification ... with title ...'` with a 10 s timeout and is gated on `sys.platform == "darwin"`.
2. Sound: `macos_play_sound()` (`grok_loop_app.py:333-342`) plays `/System/Library/Sounds/Glass.aiff` via `afplay`. If the file is missing, it silently no-ops.
3. Phone push: `ntfy_push(topic, title, body, log)` (`grok_loop_app.py:345-361`) POSTs to `https://ntfy.sh/<topic>` with `Priority: urgent`. Topic comes from `AppConfig.ntfy_topic` (set in the GUI). Empty topic = no-op.
4. Tk requirement: the venv's Python must include `_tkinter`. Verify with `python3 -c "import tkinter"`. The repo's onboarding doc (`plans/ONBOARDING_CHECKLIST.txt`) standardises on `/usr/bin/python3 -m venv .venv` because the system Python ships Tcl/Tk; some Homebrew Pythons do not.
5. Path overrides via env vars (read at module load — `grok_loop_app.py:172-180`): `GROK_LOOP_URL`, `GROK_STORAGE`, `GROK_STATE_JSON`, `GROK_HANDOFFS`, `GROK_SPECS`, `GROK_DEBUG_SCREENSHOTS`, `GROK_SELECTORS_JSON`. Use these for local tests rather than editing constants.

## File references
- `grok_loop_app.py:172-180` — env-var-backed path constants.
- `grok_loop_app.py:313-361` — `macos_notify`, `macos_play_sound`, `ntfy_push`.
- `grok_loop_app.py:1113-1124` — canonical "all three at once" pattern for the safety-phrase trigger (toast + sound + ntfy).

## Gotchas
- The repo lives on `/Volumes/External SSD/dev/...`; old Cursor agent history may reference `/Users/<you>/...` paths. See `.cursor/chat-path-migration.md` before pasting commands from old chats.
- iCloud / Downloads can briefly lock files; that's why `read_file_retry` retries 8× at 0.25 s. Don't replace it with a single `read_text()`.
- macOS Gatekeeper does **not** require Accessibility permissions for Playwright Chromium when launched as a script (per the design notes at `grok_loop_app.py:66-68`). If a future change requires them, document it here.
- `osascript` and `afplay` are best-effort; `OSError` is caught and logged at warning. Don't escalate to `error` — silent fallback is intentional on non-mac dev machines.
- `ntfy.sh` is a third-party service over plain HTTPS POST; never push secrets in the title/body. The current call only sends a generic safety-phrase message.
