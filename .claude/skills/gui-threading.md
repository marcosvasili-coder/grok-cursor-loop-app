# GUI + Threading Skill

## When to use
- You are adding a button, status update, log line, or tray menu item.
- You need to send work from the UI/tray to the worker, or push a message from the worker back to the UI.
- A change risks calling Tk from a background thread (it will crash or hang on macOS).
- You are wiring a new long-running operation that must respect **Stop** / **Kill Playwright**.

## Steps
1. Decide which thread owns the new work:
   - **Tk main thread**: anything touching widgets (`tk.*`, `ttk.*`, `messagebox`, `scrolledtext`).
   - **pystray daemon thread**: only menu callbacks; they must enqueue and return fast.
   - **watchdog daemon thread**: `FeedbackHandler.on_created` / `on_modified` only; enqueue paths.
   - **Single automation worker thread**: every Playwright call.
2. Cross-thread plumbing:
   - UI → worker: `controller.submit_cmd("name", *args)` (puts onto `cmd_queue`, drained by `process_cmd_queue` every 200 ms — `grok_loop_app.py:906-920`).
   - Worker → UI: `controller.post_ui(fn, *args)` which wraps `root.after(0, ...)` (`grok_loop_app.py:860-869`).
   - Watchdog → worker: enqueue paths via `_enqueue_handoff` → `ui_queue` → `handoff_queue` (`grok_loop_app.py:973-1006`).
3. Cooperative cancellation: any worker loop must call `auto._check_stop()` (or check `self.stop_event.is_set()`) inside the inner loop, with a small `wait_for_timeout(...)` so Stop reacts within a second.
4. Add buttons via the `btn(...)` helper inside `_build_ui` (`grok_loop_app.py:1236-1249`); wire them through `submit_cmd` rather than calling worker code directly.
5. Persist any new user-facing setting on `AppConfig` (`grok_loop_app.py:264-294`) and read/write it in `_save_ui_to_config` (`grok_loop_app.py:1456-1470`) so it survives restarts.

## File references
- `grok_loop_app.py:835-921` — `LoopController` queue setup, `post_ui`, `submit_cmd`, `process_cmd_queue`.
- `grok_loop_app.py:1148-1610` — `GrokLoopApp`: Tk setup, dark-mode styling, tray bootstrap, quit/teardown order.
- `grok_loop_app.py:1548-1588` — `_ensure_tray`: pystray icon + menu wiring; tray callbacks always enqueue commands.

## Gotchas
- Calling `messagebox.*` from a worker thread will deadlock on macOS Tahoe. Always wrap with `post_ui`.
- `tk.TclError` is caught silently inside `_safe_call` and `_safe_topmost`; it fires when the window is destroyed mid-callback. Preserve those try/except blocks.
- `start_minimized_to_tray` must check that `pystray` and `Pillow` actually imported — see `_try_start_minimized_to_tray` (`grok_loop_app.py:1484-1503`). Hiding the window without a working tray icon strands the user.
- `on_quit` order matters: stop loop → set stop_event → close automation → join worker (timeout 12 s) → stop tray → save config → destroy root (`grok_loop_app.py:1593-1610`). Reordering can leave Chromium running.
- Log buffer is bounded at 2000 lines (`grok_loop_app.py:871-875`). Don't append directly to `log_widget` from background threads — use `controller.append_log(...)`.
- Combobox is disabled while running (`on_start` / `on_stop`) so the user can't change project mid-cycle. Preserve that.
