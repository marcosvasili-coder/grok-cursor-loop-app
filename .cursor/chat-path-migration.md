# Cursor / Agent chats and old paths

This repo was moved from **`~/…` on the internal disk** to **`/Volumes/External SSD/dev/…`**.

- **Composer, Agent, and retrieval metadata** may still *mention* the old absolute paths in history. That does not change how Git or the code works today.
- **Canonical workspace** for this project: open the folder on **External SSD** (`/Volumes/External SSD/dev/<this-folder>`), not a deleted copy under `/Users/…`.
- If you paste a command or path from an old chat, **rewrite** `/Users/<you>/<old-folder>` → this repo’s path on the SSD before running it.
- To fix Cursor UI (terminals, sidebar cwd, stale `~/…` references), see the migration kit **`nvme-repo-migration`** runbook: `RUNBOOK.txt` (steps 11+), especially `fix-cursor-all-vscdb-paths.py` and `migrate-cursor-global-state-vscdb.py` — run with **Cursor quit**.

This file is installed by `install-cursor-chat-path-note.sh`; safe to commit or add to `.gitignore` if you prefer it machine-local only.
