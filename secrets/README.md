# Local secrets (not committed)

Everything in this folder is **ignored by git** except this `README.md` and `example.env`.

`local.env` is created for you as an **empty template** (also gitignored). Put values there **yourself** if you want a local record — never commit it.

Use it for **your machine only** — API keys, personal notes, or copies of config you do not want in the repo.

## Grok Cursor Loop

The app does **not** read files from this folder. Authentication is meant to work via:

1. **First-run login** in the Playwright browser window  
2. **Saved session**: `.playwright/grok_storage.json` (already gitignored at repo root)

Do **not** paste live passwords into tracked files. If you keep a private env file here, add it with a unique name (e.g. `local.env`) and never commit it.

See `example.env` for placeholder variable names only.
