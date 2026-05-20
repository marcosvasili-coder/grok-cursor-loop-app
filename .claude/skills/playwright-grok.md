# Playwright + Grok Skill

## When to use
- Grok web UI selectors break and the app fails to find the composer, file input, send button, or assistant message container.
- The "saved session expired — opening a visible browser" path keeps firing even after a fresh login.
- You are adding a new step to the upload → prompt → download cycle in `GrokAutomation`.
- Anything that touches `_launch`, `navigate_grok`, `wait_until_ready_for_chat`, `wait_for_composer`, or `_login_wall_visible`.

## Steps
1. Reproduce headed: in the GUI, uncheck **Headless browser** (or set `headless=False` in `.grok_loop_state.json`) and click **Start Automatic Loop** with a sample file in `plans/handoffs/feedback-test.md`.
2. If selectors look wrong, open Grok with Chromium DevTools and copy a stable selector — prefer `[data-testid=...]`, `aria-label`, or `role`. The current `SELECTORS` dict lives at `grok_loop_app.py:207-225`.
3. Override without editing Python: create `grok_selectors.json` at repo root with string keys matching `SELECTORS` (`file_input`, `composer`, `send_button`, `assistant_message`). Path can also be set via `GROK_SELECTORS_JSON=`. Merge logic is at `grok_loop_app.py:228-242`.
4. Re-run one handoff. Watch the live log; the line `Chat composer ready (signed-in chat).` confirms the composer is found.
5. Force a clean session if cookies are stale: `rm .playwright/grok_storage.json` and relaunch — a visible browser opens for login.
6. To force-relaunch headed mid-session, the worker calls `auto.force_headed_relaunch()` (`grok_loop_app.py:655-662`); use the same path if you add new recovery flows.

## File references
- `grok_loop_app.py:207-242` — `SELECTORS` dict and `merge_selectors_from_json`.
- `grok_loop_app.py:477-828` — `GrokAutomation` class: lifecycle, login detection, composer/upload/send/wait, downloads.
- `grok_loop_app.py:1066-1141` — `LoopController._process_one_handoff` shows the canonical end-to-end call order.

## Gotchas
- `composer` selector deliberately avoids bare `textarea` / generic `div[contenteditable]` — those match login pages and would type the prompt before sign-in. Keep that constraint when adding fallback selectors.
- `_login_wall_visible` checks both URL hints (`LOGIN_HOST_HINTS` at `grok_loop_app.py:183-193`) and a visible `input[type="password"]`. URL-only checks miss in-page Grok sign-in.
- `STORAGE_STATE_PATH` is loaded into `new_context(storage_state=...)` only at `_launch`; calling `save_storage()` mid-session writes back, but you must call it before `close()` or you log the user out (see the explicit save in `GrokAutomation.close`, `grok_loop_app.py:499-505`).
- `expect_download` is wrapped in `bounded_expect_download` (`grok_loop_app.py:678-687`) and **swallows** `PlaywrightTimeoutError` on purpose — Grok often returns links instead of downloads.
- `set_default_timeout(120_000)` is set per page; long-running waits (`wait_for_new_assistant_text`, `wait_until_ready_for_chat`) use their own deadlines and must call `self._check_stop()` inside loops so **Stop** is responsive.
- All Playwright calls must run on the worker thread. Calling Playwright sync API from the Tk main thread will deadlock or crash.
