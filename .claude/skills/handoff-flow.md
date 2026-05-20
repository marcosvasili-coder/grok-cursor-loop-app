# Handoff Flow Skill

## When to use
- You are changing how feedback files are picked up, processed, or counted toward `max_iterations`.
- You are adjusting download capture, artefact naming, or where files land under `plans/grok-pm-specs/`.
- You need to add or change a safety-phrase trigger or its notification path (macOS toast, sound, ntfy).
- You are debugging "file dropped but never processed" or duplicate-processing reports.

## Steps
1. Drop a sample file matching `feedback-*.md` into `plans/handoffs/`. Anything not matching that exact prefix and `.md` suffix is ignored by `FeedbackHandler._handle` (`grok_loop_app.py:431-441`).
2. Existing files are seeded oldest-first when **Start Automatic Loop** is clicked — see `_seed_existing_handoffs` (`grok_loop_app.py:976-996`). New files arrive via watchdog `on_created` / `on_modified`.
3. Per-file pipeline (`_process_one_handoff`, `grok_loop_app.py:1066-1141`):
   1. `read_file_retry` — 8 attempts, 0.25 s delay (handles iCloud / Downloads file locks).
   2. `auto.ensure_browser(prefer_headed=...)` — headed if no valid storage_state OR Headless is unchecked.
   3. `navigate_grok` → `wait_until_ready_for_chat` → `save_storage`.
   4. `upload_markdown(md_path)` → 1.5 s settle → capture `baseline = _last_assistant_text()`.
   5. `send_pm_prompt("[Project: <proj>]\n\n<pm_prompt>")` → `bounded_expect_download(8000)`.
   6. `wait_for_new_assistant_text(baseline, 600s)` → `bounded_expect_download(25000)` → `collect_extra_downloads(20s)`.
   7. `safety_triggered(text)` checks `SAFETY_PHRASES` (`grok_loop_app.py:249-254`) — on hit: status → paused, `macos_play_sound`, `macos_notify`, `ntfy_push`, `stop_event.set()`.
4. Downloads route through `DownloadCollector.handler` (`grok_loop_app.py:459-474`) and land at `plans/grok-pm-specs/<UTC-timestamp>__<sanitised-name>` via `specs_save_path` (`grok_loop_app.py:408-410`).
5. To add a new safety phrase, append a lowercase string to `SAFETY_PHRASES` — comparison is `.lower()` substring match.

## File references
- `grok_loop_app.py:418-451` — `FeedbackHandler` watchdog handler with dedupe set + lock.
- `grok_loop_app.py:1025-1064` — `_worker_loop` main pump: blocks on `handoff_queue`, honours `max_iterations`, drives one handoff at a time.
- `grok_loop_app.py:1066-1141` — `_process_one_handoff` end-to-end pipeline (canonical order; copy this when adding steps).

## Gotchas
- Files are deduped by absolute resolved path (`Path.resolve()`); editing a file in place fires `on_modified`, but the `_seen` set blocks reprocessing. Rename to a new `feedback-<id>.md` if you want a re-run.
- A failed handoff still counts toward `max_iterations` (`_process_one_handoff` returns `True` from the except branch — `grok_loop_app.py:1130-1140`). That's deliberate so a wedged Grok page doesn't loop forever.
- Safety trigger sets `stop_event` — do **not** rely on it to also clear `self._running`; the worker's `finally` does that (`grok_loop_app.py:1015-1023`).
- `ntfy_push` swallows `URLError` and logs at warning. Empty topic is a no-op. Don't add hard failures here — phones being offline must not block automation.
- `read_file_retry` returns `None` (not raise) on persistent failure; check the return value before using it.
- The watcher is non-recursive (`recursive=False`). Subdirectories under `plans/handoffs/` are ignored on purpose.
