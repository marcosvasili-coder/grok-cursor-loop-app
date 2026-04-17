#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
GROK CURSOR LOOP — SETUP (macOS, Python 3.10+)
================================================================================
Install dependencies:
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt
  playwright install chromium

ntfy.sh (phone push on safety stop):
  - Install the ntfy app or use https://ntfy.sh in a browser.
  - Pick a secret topic name; enter it in the GUI.
  - Optional test: curl -d "test" https://ntfy.sh/YOUR_TOPIC

First-run login (SuperGrok / Grok web):
  - With no saved session file, the app opens a visible Chromium window.
  - Log in to Grok in that window; when the chat UI loads, automation continues
    and saves cookies to ./.playwright/grok_storage.json (gitignored).

Folders (created if missing):
  ./plans/handoffs/          — drop feedback-*.md here
  ./plans/grok-pm-specs/     — downloaded artefacts land here (timestamped)

Run:
  python3 grok_loop_app.py

Manual onboarding (first login + handoff test):
  See plans/ONBOARDING_CHECKLIST.txt (use .venv built with a Python that has tkinter).

Optional smoke check (imports + folders, no network):
  python3 scripts/smoke_check.py

Selector overrides (optional):
  Create ./grok_selectors.json with string keys matching SELECTORS (file_input, composer,
  send_button, assistant_message) to tune the UI without editing Python. Env:
  GROK_SELECTORS_JSON=/path/to/file.json

Python build note (macOS):
  Use a Python that bundles Tcl/Tk (e.g. python.org installer). Verify with:
    python3 -c "import tkinter"
  Some Homebrew Pythons omit _tkinter; if that fails, use another Python or install
  your OS/Homebrew Tcl/Tk bindings for your Python version.

================================================================================
ARCHITECTURE (internal plan — threading, state, errors)
================================================================================
Threading:
  - Main thread: Tkinter GUI only (required by Tk).
  - pystray: runs its icon loop in a daemon thread; actions enqueue commands.
  - Watchdog Observer: daemon thread; enqueues feedback file paths (FIFO).
  - Single automation worker thread: owns Playwright sync API (browser/context/page).
  - Cross-thread: queue.Queue + threading.Event; UI updates via root.after(0, ...).

State:
  - AppConfig persisted in ./.grok_loop_state.json (last project, ntfy topic, etc.).
  - Session: ./.playwright/grok_storage.json via Playwright storage_state.
  - Runtime flags: running, stop_requested, kill_browser, iteration counts.

Errors:
  - Worker boundary try/except; log full traceback; friendly status line; no crash of Tk.
  - Network/offline: catch and backoff; user can Stop.

macOS (Tahoe):
  - Not sandboxed as a script; no special Accessibility for Playwright Chromium.
  - Toasts: osascript display notification; sound: afplay.
  - iCloud/Downloads paths may lock files — we retry reads.

Cookies / session:
  - First run: headed browser until chat UI detected, then save storage_state.
  - Next runs: load storage_state; if still on login, log and open headed fallback.

Artefact downloads:
  - context.on("download") + page.expect_download with timeouts after send.
  - Files saved under ./plans/grok-pm-specs/ with UTC timestamp prefix.

================================================================================
EDGE CASES & RISKS (addressed in code)
================================================================================
- No internet / slow UI: step timeouts, clear log lines, Stop/Kill.
- Grok UI changes: SELECTORS dict at top — edit and re-run.
- Multiple feedback files: single queue; one Playwright job at a time.
- Browser crash/hang: Kill Playwright; worker closes context.
- File locks: retry read with backoff.
- Tray vs GUI: commands serialized through controller queue.

================================================================================
MANUAL TESTING CHECKLIST (comments only)
================================================================================
1) Delete .playwright/grok_storage.json → launch → login in browser → session saved.
2) Start loop → add plans/handoffs/feedback-test.md → upload + prompt + downloads.
3) Mock: assistant text containing a safety phrase → pause + red status + notify.
4) ntfy: publish to topic from another device; confirm phone receives on stop phrase.
5) Minimize / use tray Start-Stop-Status; window hide/show.
6) Stop during an active step; verify clean shutdown.
7) Change project while idle OK; while running combobox disabled.
8) With a saved session file, force expiry (or delete cookies in browser) — headed
   fallback should open once and recover after login.

================================================================================
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

# --- Third-party (see requirements.txt) --------------------------------------
try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore

try:
    import pystray
    from pystray import MenuItem as TrayMenuItem
except ImportError:
    pystray = None  # type: ignore
    TrayMenuItem = None  # type: ignore

try:
    from playwright.sync_api import (
        Browser,
        BrowserContext,
        Page,
        Playwright,
        TimeoutError as PlaywrightTimeoutError,
        sync_playwright,
    )
except ImportError:
    sync_playwright = None  # type: ignore
    PlaywrightTimeoutError = Exception  # type: ignore

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:
    FileSystemEventHandler = object  # type: ignore
    Observer = None  # type: ignore

import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

# =============================================================================
# CONFIGURABLE SELECTORS — update if Grok web UI changes
#
# How to update when Grok breaks:
#   1) Open Grok in Chromium DevTools, find the real textarea / file input / assistant
#      container, copy a stable CSS selector (prefer [data-testid], role, or id).
#   2) Edit SELECTORS below, OR put overrides in grok_selectors.json (see header).
#   3) Re-run one handoff with Headless off if you need to watch the browser.
# =============================================================================

GROK_CHAT_URL = os.environ.get("GROK_LOOP_URL", "https://grok.com/")
STORAGE_STATE_PATH = Path(os.environ.get("GROK_STORAGE", ".playwright/grok_storage.json"))
STATE_JSON_PATH = Path(os.environ.get("GROK_STATE_JSON", ".grok_loop_state.json"))
HANDOFFS_DIR = Path(os.environ.get("GROK_HANDOFFS", "plans/handoffs"))
SPECS_DIR = Path(os.environ.get("GROK_SPECS", "plans/grok-pm-specs"))
DEBUG_SCREENSHOT_DIR = Path(
    os.environ.get("GROK_DEBUG_SCREENSHOTS", "plans/debug/screenshots")
)
SELECTORS_JSON_PATH = Path(os.environ.get("GROK_SELECTORS_JSON", "grok_selectors.json"))

# Login / OAuth detection (URL substring match)
LOGIN_HOST_HINTS = (
    "accounts.x.ai",
    "sign-in",
    "signin",
    "oauth",
    "login",
    "x.com/i/flow",
    "twitter.com/i/flow",
    "apple.com/auth",
    "google.com/o/oauth",
)


def storage_state_looks_valid() -> bool:
    """Non-empty Playwright storage_state JSON (avoids trusting a failed write)."""
    if not STORAGE_STATE_PATH.is_file():
        return False
    try:
        return STORAGE_STATE_PATH.stat().st_size >= 80
    except OSError:
        return False

# Composer / chat — avoid bare "textarea" or generic contenteditable: those match login pages
# and the app would type before Grok is signed in. Override via grok_selectors.json if Grok changes.
SELECTORS = {
    "file_input": 'input[type="file"]',
    "composer": (
        'textarea[placeholder*="Ask"], textarea[placeholder*="ask"], '
        'textarea[placeholder*="Message"], textarea[placeholder*="message"], '
        'textarea[data-testid="composer"], [data-testid="composer"] textarea, '
        'div[contenteditable="true"][data-testid*="composer"], '
        'div[contenteditable="true"][aria-label*="Ask"], '
        'div[contenteditable="true"][aria-label*="message"]'
    ),
    "send_button": (
        'button[aria-label*="Send"], button[type="submit"], '
        'button:has-text("Send"), [data-testid*="send"]'
    ),
    "assistant_message": (
        '[data-message-author="assistant"], [data-role="assistant"], '
        'div[data-test="assistant"], article, [class*="assistant"]'
    ),
}


def merge_selectors_from_json(path: Path, log: logging.Logger) -> None:
    """Merge optional JSON overrides into SELECTORS (same keys, string values)."""
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("merge_selectors_from_json: %s", e)
        return
    if not isinstance(data, dict):
        return
    for key, val in data.items():
        if key in SELECTORS and isinstance(val, str) and val.strip():
            SELECTORS[key] = val.strip()
            log.info("Selector override from %s: %s", path, key)

DEFAULT_PM_PROMPT = (
    "PM mode: Review coder feedback, incorporate changes, propose updates if needed, "
    "generate next spec + updated PPTX deck."
)

SAFETY_PHRASES = [
    "human sign off required",
    "ready for human review",
    "agreed & ready to code",
    "human approval needed",
]

SOUND_FILE = "/System/Library/Sounds/Glass.aiff"

# =============================================================================
# Data & logging
# =============================================================================


@dataclass
class AppConfig:
    projects: List[str] = field(default_factory=lambda: ["default"])
    last_project: str = "default"
    pm_prompt: str = DEFAULT_PM_PROMPT
    max_iterations: int = 8
    ntfy_topic: str = ""
    auto_launch_loop: bool = False
    headless: bool = True
    start_minimized_to_tray: bool = False
    screenshot_on_failure: bool = False

    def to_json(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_json(data: Dict[str, Any]) -> "AppConfig":
        cfg = AppConfig()
        if not isinstance(data, dict):
            return cfg
        cfg.projects = list(data.get("projects") or cfg.projects)
        cfg.last_project = str(data.get("last_project") or cfg.last_project)
        cfg.pm_prompt = str(data.get("pm_prompt") or cfg.pm_prompt)
        cfg.max_iterations = int(data.get("max_iterations") or cfg.max_iterations)
        cfg.ntfy_topic = str(data.get("ntfy_topic") or "")
        cfg.auto_launch_loop = bool(data.get("auto_launch_loop", False))
        cfg.headless = bool(data.get("headless", True))
        cfg.start_minimized_to_tray = bool(data.get("start_minimized_to_tray", False))
        cfg.screenshot_on_failure = bool(data.get("screenshot_on_failure", False))
        if cfg.last_project not in cfg.projects and cfg.projects:
            cfg.last_project = cfg.projects[0]
        return cfg


def setup_logging() -> logging.Logger:
    log = logging.getLogger("grok_loop")
    log.setLevel(logging.DEBUG)
    if not log.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        )
        log.addHandler(h)
    return log


LOG = setup_logging()
merge_selectors_from_json(SELECTORS_JSON_PATH, LOG)


def macos_notify(title: str, message: str) -> None:
    if sys.platform != "darwin":
        LOG.info("notify: %s — %s", title, message)
        return
    script = (
        f'display notification {json.dumps(message)} '
        f'with title {json.dumps(title)}'
    )
    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except OSError as e:
        LOG.warning("osascript failed: %s", e)


def macos_play_sound() -> None:
    if sys.platform != "darwin":
        return
    path = SOUND_FILE if os.path.isfile(SOUND_FILE) else None
    if not path:
        return
    try:
        subprocess.Popen(["afplay", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        LOG.warning("afplay: %s", e)


def ntfy_push(topic: str, title: str, body: str, log: logging.Logger) -> None:
    topic = (topic or "").strip()
    if not topic:
        return
    url = f"https://ntfy.sh/{urllib.parse.quote(topic, safe='')}"
    data = f"{title}\n{body}".encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Title": title, "Priority": "urgent"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            log.debug("ntfy status %s", resp.status)
    except urllib.error.URLError as e:
        log.warning("ntfy failed: %s", e)


def ensure_dirs() -> None:
    HANDOFFS_DIR.mkdir(parents=True, exist_ok=True)
    SPECS_DIR.mkdir(parents=True, exist_ok=True)
    STORAGE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


def load_config(path: Path) -> AppConfig:
    if not path.is_file():
        return AppConfig()
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return AppConfig.from_json(data)
    except (json.JSONDecodeError, OSError) as e:
        LOG.warning("load_config: %s", e)
        return AppConfig()


def save_config(path: Path, cfg: AppConfig) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(cfg.to_json(), f, indent=2)
    except OSError as e:
        LOG.error("save_config: %s", e)


def read_file_retry(path: Path, attempts: int = 8, delay: float = 0.25) -> Optional[str]:
    last_err: Optional[BaseException] = None
    for _ in range(attempts):
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            last_err = e
            time.sleep(delay)
    LOG.error("read_file_retry failed for %s: %s", path, last_err)
    return None


def timestamp_prefix() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def specs_save_path(original_name: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", original_name).strip("._") or "download"
    return SPECS_DIR / f"{timestamp_prefix()}__{safe}"


# =============================================================================
# Watchdog — feedback files
# =============================================================================


class FeedbackHandler(FileSystemEventHandler):
    def __init__(
        self,
        enqueue: Callable[[Path], None],
        log: logging.Logger,
        seen: Set[str],
    ) -> None:
        super().__init__()
        self._enqueue = enqueue
        self._log = log
        self._seen = seen
        self._lock = threading.Lock()

    def _handle(self, p: Path) -> None:
        if not p.name.startswith("feedback-") or not p.name.endswith(".md"):
            return
        key = str(p.resolve())
        with self._lock:
            if key in self._seen:
                return
            self._seen.add(key)
        if p.is_file():
            self._log.info("Queued handoff: %s", p)
            self._enqueue(p)

    def on_created(self, event: Any) -> None:  # type: ignore[override]
        if getattr(event, "is_directory", False):
            return
        self._handle(Path(event.src_path))

    def on_modified(self, event: Any) -> None:  # type: ignore[override]
        if getattr(event, "is_directory", False):
            return
        self._handle(Path(event.src_path))


# =============================================================================
# Grok / Playwright (worker thread only)
# =============================================================================


class DownloadCollector:
    def __init__(self, log: logging.Logger) -> None:
        self._log = log
        self.paths: List[Path] = []
        self._saved: Set[str] = set()

    def handler(self, download: Any) -> None:
        try:
            suggested = download.suggested_filename or "download.bin"
            dest = specs_save_path(suggested)
            download.save_as(str(dest))
            self.paths.append(dest)
            self._saved.add(str(dest))
            self._log.info("Saved download: %s", dest)
        except Exception as e:
            self._log.error("download save error: %s", e)


class GrokAutomation:
    """Playwright operations — call only from the automation worker thread."""

    def __init__(
        self,
        log: logging.Logger,
        stop_event: threading.Event,
        headless_default: bool,
    ) -> None:
        self._log = log
        self._stop = stop_event
        self._headless_default = headless_default
        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._download_collector = DownloadCollector(log)

    def _check_stop(self) -> None:
        if self._stop.is_set():
            raise RuntimeError("Stopped by user")

    def close(self) -> None:
        # Persist cookies before tearing down (Stop/Quit used to log users out otherwise).
        try:
            if self._context:
                self.save_storage()
        except Exception as e:
            self._log.debug("save_storage before close: %s", e)
        try:
            if self._context:
                self._context.close()
        except Exception as e:
            self._log.debug("context close: %s", e)
        try:
            if self._browser:
                self._browser.close()
        except Exception as e:
            self._log.debug("browser close: %s", e)
        try:
            if self._pw:
                self._pw.stop()
        except Exception as e:
            self._log.debug("playwright stop: %s", e)
        self._context = None
        self._browser = None
        self._page = None
        self._pw = None

    def kill_hard(self) -> None:
        self.close()

    def _launch(self, headless: bool) -> None:
        if sync_playwright is None:
            raise RuntimeError("playwright is not installed")
        self._pw = sync_playwright().start()
        assert self._pw is not None
        self._browser = self._pw.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        storage: Optional[Path] = None
        if STORAGE_STATE_PATH.is_file():
            storage = STORAGE_STATE_PATH
        self._context = self._browser.new_context(
            storage_state=str(storage) if storage else None,
            accept_downloads=True,
        )
        self._context.on("download", self._download_collector.handler)
        self._page = self._context.new_page()
        self._page.set_default_timeout(120_000)

    def ensure_browser(self, prefer_headed: bool) -> None:
        self._check_stop()
        if self._page:
            return
        headless = self._headless_default and not prefer_headed
        self._launch(headless=headless)

    def save_storage(self) -> None:
        if not self._context:
            return
        try:
            STORAGE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            self._context.storage_state(path=str(STORAGE_STATE_PATH))
            self._log.info("Session saved to %s", STORAGE_STATE_PATH)
        except Exception as e:
            self._log.error("save_storage: %s", e)

    def _is_login_url(self, url: str) -> bool:
        u = url.lower()
        if any(h in u for h in LOGIN_HOST_HINTS):
            return True
        # Logged-out Grok sometimes stays on grok.com with /sign-in or similar in path
        if "grok.com" in u and any(
            p in u for p in ("/sign-in", "/signin", "/login", "/i/flow")
        ):
            return True
        return False

    def _login_wall_visible(self) -> bool:
        """True if the page still looks like a login / sign-up flow (do not type into chat)."""
        assert self._page is not None
        if self._is_login_url(self._page.url):
            return True
        try:
            pw = self._page.locator('input[type="password"]:visible').first
            if pw.count() > 0 and pw.is_visible():
                return True
        except Exception:
            pass
        return False

    def navigate_grok(self) -> None:
        assert self._page is not None
        self._page.goto(GROK_CHAT_URL, wait_until="domcontentloaded")
        # Give SPA / redirects time (OAuth can bounce URLs quickly)
        self._page.wait_for_timeout(3000)

    def wait_until_ready_for_chat(self, timeout_ms: int = 45 * 60 * 1000) -> None:
        """
        Wait until the chat composer is visible — keeps waiting while you sign in.
        Saves storage_state periodically so partial OAuth progress is not lost if you Stop.
        """
        assert self._page is not None
        deadline = time.time() + timeout_ms / 1000.0
        last_log = 0.0
        last_save = 0.0
        self._log.info(
            "Waiting for Grok chat UI. If you see a login or OAuth screen, complete it in "
            "the browser; this step can take several minutes."
        )
        while time.time() < deadline:
            self._check_stop()
            now = time.time()
            if now - last_save >= 25.0:
                self.save_storage()
                last_save = now
            url = self._page.url
            if self._is_login_url(url):
                if now - last_log >= 20.0:
                    self._log.info(
                        "Still on sign-in / OAuth ( %s ) — finish logging in; waiting…",
                        url[:80],
                    )
                    last_log = now
            elif now - last_log >= 45.0:
                self._log.info("Waiting for chat composer…")
                last_log = now

            if self._login_wall_visible():
                self._page.wait_for_timeout(500)
                continue

            for sel in SELECTORS["composer"].split(", "):
                sel = sel.strip()
                if not sel:
                    continue
                loc = self._page.locator(sel).first
                try:
                    if loc.count() > 0 and loc.is_visible():
                        self._log.info("Chat composer ready (signed-in chat).")
                        self.save_storage()
                        return
                except Exception:
                    continue
            self._page.wait_for_timeout(500)

        raise TimeoutError(
            "Chat composer did not appear in time — try Headless off, complete login, "
            "or update SELECTORS in grok_selectors.json"
        )

    def still_on_login(self) -> bool:
        if not self._page:
            return True
        return self._is_login_url(self._page.url)

    def force_headed_relaunch(self) -> None:
        """Close browser and reopen visible Chromium (session file still applied on next launch)."""
        self._log.warning(
            "Session expired or invalid — reopening a visible browser once. "
            "Log in to Grok; when chat loads, the session file is refreshed."
        )
        self.close()
        self._launch(headless=False)

    def save_failure_screenshot(self, tag: str) -> Optional[Path]:
        if not self._page:
            return None
        DEBUG_SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", tag)[:80] or "error"
        path = DEBUG_SCREENSHOT_DIR / f"{timestamp_prefix()}__{safe}.png"
        try:
            self._page.screenshot(path=str(path), full_page=True)
            self._log.info("Debug screenshot: %s", path)
            return path
        except Exception as e:
            self._log.warning("save_failure_screenshot: %s", e)
            return None

    def bounded_expect_download(self, timeout_ms: int) -> None:
        """Wait up to *timeout_ms* for a download to start (pairs with context listener)."""
        assert self._page is not None
        try:
            with self._page.expect_download(timeout=timeout_ms):
                self._page.wait_for_timeout(timeout_ms)
        except PlaywrightTimeoutError:
            self._log.debug(
                "No download in %sms window (OK if Grok only shows links).", timeout_ms
            )

    def wait_for_composer(self, timeout_ms: int = 300_000) -> "object":
        assert self._page is not None
        deadline = time.time() + timeout_ms / 1000.0
        last_log = 0.0
        while time.time() < deadline:
            self._check_stop()
            if self._login_wall_visible():
                now = time.time()
                if now - last_log > 10:
                    self._log.info("Login screen detected — finish signing in; not typing yet.")
                    last_log = now
                self._page.wait_for_timeout(500)
                continue
            for sel in SELECTORS["composer"].split(", "):
                sel = sel.strip()
                if not sel:
                    continue
                loc = self._page.locator(sel).first
                try:
                    if loc.count() > 0 and loc.is_visible():
                        return loc
                except Exception:
                    continue
            now = time.time()
            if now - last_log > 10:
                self._log.info("Waiting for chat composer… (log in if needed)")
                last_log = now
            self._page.wait_for_timeout(500)
        raise TimeoutError("Chat composer not found — check SELECTORS or complete login")

    def upload_markdown(self, md_path: Path) -> None:
        assert self._page is not None
        self.wait_for_composer()
        inp = self._page.locator(SELECTORS["file_input"]).first
        if inp.count() == 0:
            raise RuntimeError("No file input found — update SELECTORS['file_input']")
        inp.set_input_files(str(md_path))

    def send_pm_prompt(self, text: str) -> None:
        assert self._page is not None
        composer = self.wait_for_composer()
        try:
            composer.click(timeout=5000)
        except Exception:
            pass
        try:
            composer.fill("")
        except Exception:
            try:
                composer.evaluate("node => { node.innerText = ''; }")
            except Exception as e:
                self._log.debug("composer clear: %s", e)
        try:
            if hasattr(composer, "press_sequentially"):
                composer.press_sequentially(text, delay=5)
            else:
                composer.type(text, delay=5)
        except Exception:
            assert self._page is not None
            self._page.keyboard.type(text, delay=5)

        # Try click send, else keyboard
        sent = False
        for part in SELECTORS["send_button"].split(", "):
            part = part.strip()
            if not part:
                continue
            btn = self._page.locator(part).first
            try:
                if btn.count() > 0 and btn.is_enabled():
                    btn.click()
                    sent = True
                    break
            except Exception:
                continue
        if not sent:
            try:
                composer.press("Enter")
            except Exception:
                self._page.keyboard.press("Enter")

    def _last_assistant_text(self) -> str:
        assert self._page is not None
        parts: List[str] = []
        for part in SELECTORS["assistant_message"].split(", "):
            part = part.strip()
            if not part:
                continue
            loc = self._page.locator(part)
            try:
                n = loc.count()
            except Exception:
                continue
            for i in range(max(0, n - 3), n):
                try:
                    t = loc.nth(i).inner_text(timeout=2000)
                    if t:
                        parts.append(t)
                except Exception:
                    continue
        return "\n".join(parts) if parts else ""

    def wait_for_new_assistant_text(
        self, baseline: str, timeout_sec: float = 600.0
    ) -> str:
        """Wait until assistant area differs from *baseline* and stops changing briefly."""
        assert self._page is not None
        deadline = time.time() + timeout_sec
        stable_count = 0
        last_text = ""
        baseline_norm = (baseline or "").strip()
        while time.time() < deadline:
            self._check_stop()
            text = self._last_assistant_text()
            if (text or "").strip() == baseline_norm:
                self._page.wait_for_timeout(400)
                continue
            if text == last_text:
                stable_count += 1
            else:
                stable_count = 0
                last_text = text
            if stable_count >= 4:
                return text
            self._page.wait_for_timeout(400)
        self._log.warning("Response wait timeout — returning last assistant text seen")
        return last_text

    def collect_extra_downloads(self, wait_sec: float = 15.0) -> None:
        """Wait window for async downloads fired by the UI."""
        assert self._page is not None
        end = time.time() + wait_sec
        while time.time() < end:
            self._check_stop()
            self._page.wait_for_timeout(500)

    def safety_triggered(self, assistant_text: str) -> bool:
        low = assistant_text.lower()
        return any(p in low for p in SAFETY_PHRASES)


# =============================================================================
# Controller — worker + queues
# =============================================================================


class LoopController:
    def __init__(self, root: tk.Tk, log: logging.Logger) -> None:
        self.root = root
        self.log = log
        self.config = load_config(STATE_JSON_PATH)
        self.ui_queue: "queue.Queue[tuple[str, tuple[Any, ...]]]" = queue.Queue()
        self.cmd_queue: "queue.Queue[tuple[str, tuple[Any, ...]]]" = queue.Queue()

        self.stop_event = threading.Event()
        self.worker_thread: Optional[threading.Thread] = None
        self.observer: Optional[Any] = None
        self.seen_files: Set[str] = set()

        self._running = False
        self._iterations_done = 0
        self._tray_icon: Any = None
        self._tray_ready = threading.Event()

        self.status_var = tk.StringVar(value="[Idle] Ready")
        self.log_lines: List[str] = []

        self._automation: Optional[GrokAutomation] = None
        self.handoff_queue: "queue.Queue[Path]" = queue.Queue()

    # --- UI thread helpers -------------------------------------------------
    def post_ui(self, fn: Callable[..., None], *args: Any) -> None:
        self.root.after(0, lambda: self._safe_call(fn, *args))

    def _safe_call(self, fn: Callable[..., None], *args: Any) -> None:
        try:
            fn(*args)
        except tk.TclError:
            pass
        except Exception as e:
            self.log.error("UI callback: %s", e)

    def append_log(self, msg: str) -> None:
        self.log_lines.append(msg)
        if len(self.log_lines) > 2000:
            self.log_lines = self.log_lines[-2000:]
        self.post_ui(self._append_log_widget, msg)

    def _append_log_widget(self, msg: str) -> None:
        if hasattr(self, "log_widget"):
            self.log_widget.configure(state="normal")
            self.log_widget.insert(tk.END, msg + "\n")
            self.log_widget.see(tk.END)
            self.log_widget.configure(state="disabled")

    def set_status(self, text: str, kind: str = "idle") -> None:
        """kind: idle | running | paused | error | normal (no prefix, legacy)."""

        def _apply() -> None:
            styles: Dict[str, tuple[str, str]] = {
                "idle": ("[Idle] ", "#a8a8a8"),
                "running": ("[Running] ", "#9ed9b8"),
                "paused": ("[Paused] ", "#ffb347"),
                "error": ("[Error] ", "#ff6b6b"),
                "normal": ("", "#eaeaea"),
            }
            prefix, fg = styles.get(kind, styles["idle"])
            self.status_var.set(f"{prefix}{text}")
            if hasattr(self, "status_label"):
                self.status_label.configure(fg=fg)

        self.post_ui(_apply)

    # --- Commands from GUI / tray -----------------------------------------
    def submit_cmd(self, name: str, *args: Any) -> None:
        self.cmd_queue.put((name, args))

    def process_cmd_queue(self) -> None:
        try:
            while True:
                name, args = self.cmd_queue.get_nowait()
                if name == "start":
                    self._start_loop()
                elif name == "stop":
                    self._stop_loop()
                elif name == "kill":
                    self._kill_browser()
                elif name == "tray_status":
                    macos_notify("Grok Loop", self.status_var.get())
        except queue.Empty:
            pass
        self.root.after(200, self.process_cmd_queue)

    def _start_loop(self) -> None:
        if self._running:
            self.append_log("Already running.")
            return
        ensure_dirs()
        self.stop_event.clear()
        self._running = True
        self._iterations_done = 0
        self.seen_files.clear()
        self.set_status("Starting…", "running")
        self.append_log("Automatic loop started (watching handoffs).")

        if Observer is None:
            messagebox.showerror("Error", "watchdog is not installed.")
            self._running = False
            return

        handler = FeedbackHandler(self._enqueue_handoff, self.log, self.seen_files)
        obs = Observer()
        obs.schedule(handler, str(HANDOFFS_DIR.resolve()), recursive=False)
        obs.start()
        self.observer = obs

        self._seed_existing_handoffs()

        self.worker_thread = threading.Thread(target=self._worker_main, daemon=True)
        self.worker_thread.start()

    def _stop_loop(self) -> None:
        self.append_log("Stop requested.")
        self.stop_event.set()
        self._running = False
        if self.observer:
            try:
                self.observer.stop()
                self.observer.join(timeout=5.0)
            except Exception as e:
                self.log.debug("observer stop: %s", e)
            self.observer = None
        self.set_status("Stopping…", "idle")

    def _kill_browser(self) -> None:
        self.append_log("Kill Playwright requested.")
        self.stop_event.set()
        if self._automation:
            try:
                self._automation.kill_hard()
            except Exception as e:
                self.log.error("kill: %s", e)
            self._automation = None

    def _enqueue_handoff(self, path: Path) -> None:
        self.ui_queue.put(("handoff", (str(path),)))

    def _seed_existing_handoffs(self) -> None:
        """Queue already-present feedback files (oldest first)."""
        try:
            paths = sorted(
                (
                    p
                    for p in HANDOFFS_DIR.glob("feedback-*.md")
                    if p.is_file()
                ),
                key=lambda p: p.stat().st_mtime,
            )
        except OSError as e:
            self.log.warning("seed handoffs: %s", e)
            return
        for p in paths:
            key = str(p.resolve())
            if key in self.seen_files:
                continue
            self.seen_files.add(key)
            self.handoff_queue.put(p)
            self.append_log(f"Queued existing handoff: {p.name}")

    def poll_ui_queue(self) -> None:
        try:
            while True:
                kind, payload = self.ui_queue.get_nowait()
                if kind == "handoff":
                    self.handoff_queue.put(Path(payload[0]))
        except queue.Empty:
            pass
        self.root.after(300, self.poll_ui_queue)

    def _worker_main(self) -> None:
        try:
            self._worker_loop()
        except Exception as e:
            self.log.error("worker crashed: %s\n%s", e, traceback.format_exc())
            self.post_ui(lambda: self.append_log(f"Worker error: {e}"))
            self.post_ui(lambda: self.set_status("Worker failed — see log", "error"))
        finally:
            if self._automation:
                try:
                    self._automation.close()
                except Exception:
                    pass
                self._automation = None
            self.post_ui(lambda: self.set_status("Ready", "idle"))
            self._running = False

    def _worker_loop(self) -> None:
        auto = GrokAutomation(
            self.log,
            self.stop_event,
            headless_default=self.config.headless,
        )
        self._automation = auto

        first_cycle = True
        while not self.stop_event.is_set():
            if self._iterations_done >= self.config.max_iterations:
                self.append_log(
                    f"Reached max iterations ({self.config.max_iterations}). Stopping."
                )
                self.post_ui(lambda: self.set_status("Max iterations reached", "paused"))
                macos_notify("Grok Loop", "Max iterations reached.")
                break

            # Block for next file (with wake for stop)
            path: Optional[Path] = None
            while not self.stop_event.is_set():
                try:
                    path = self.handoff_queue.get(timeout=0.5)
                    break
                except queue.Empty:
                    continue
            if self.stop_event.is_set() or path is None:
                break

            done = self._process_one_handoff(auto, path, first_cycle)
            first_cycle = False
            if done:
                self._iterations_done += 1

        try:
            if self.observer:
                self.observer.stop()
        except Exception:
            pass
        self.observer = None

    def _process_one_handoff(
        self,
        auto: GrokAutomation,
        md_path: Path,
        first_cycle: bool,
    ) -> bool:
        """Return True if this handoff counts toward max_iterations."""
        self.append_log(f"Processing: {md_path}")
        self.post_ui(lambda: self.set_status(f"Working: {md_path.name}", "running"))

        content = read_file_retry(md_path)
        if content is None:
            self.append_log(f"Could not read file (skipping): {md_path}")
            return False

        had_storage = storage_state_looks_valid()
        # Show real browser until we have a real session file, or whenever Headless is off.
        prefer_headed = (not had_storage) or (not self.config.headless)
        try:
            auto.ensure_browser(prefer_headed=prefer_headed)
            auto.navigate_grok()
            if had_storage and auto.still_on_login():
                self.append_log(
                    "Saved session expired — opening a visible browser. "
                    "Log in to Grok; session is saved when the chat UI appears."
                )
                auto.force_headed_relaunch()
                auto.navigate_grok()
            auto.wait_until_ready_for_chat()
            auto.save_storage()

            auto.upload_markdown(md_path)
            self.append_log("Uploaded feedback file.")
            auto._page.wait_for_timeout(1500)

            baseline = auto._last_assistant_text()
            proj = self.config.last_project or "default"
            body = self.config.pm_prompt.strip() or DEFAULT_PM_PROMPT
            prompt = f"[Project: {proj}]\n\n{body}"
            auto.send_pm_prompt(prompt)
            self.append_log("Sent PM prompt.")
            auto.bounded_expect_download(8000)

            assistant = auto.wait_for_new_assistant_text(baseline, timeout_sec=600.0)
            auto.bounded_expect_download(25000)
            auto.collect_extra_downloads(wait_sec=20.0)

            if auto.safety_triggered(assistant):
                self.append_log("SAFETY: Human review required — pausing.")
                self.post_ui(lambda: self.set_status("HUMAN SIGN-OFF REQUIRED", "paused"))
                macos_play_sound()
                macos_notify("Grok Loop", "Human sign-off required — review Grok output.")
                ntfy_push(
                    self.config.ntfy_topic,
                    "Grok Loop — human review",
                    "Safety phrase detected. Automation paused.",
                    self.log,
                )
                self.stop_event.set()
                return True

            self.append_log("Cycle complete.")
            self.post_ui(lambda: self.set_status("Waiting for next handoff", "idle"))
            return True
        except Exception as e:
            self.log.error("handoff error: %s\n%s", e, traceback.format_exc())
            self.append_log(f"Error: {e}")
            if self.config.screenshot_on_failure:
                shot = auto.save_failure_screenshot(md_path.name)
                if shot:
                    self.append_log(f"Debug screenshot: {shot}")
            self.post_ui(lambda: self.set_status("Handoff failed — see log", "error"))
            if prefer_headed:
                macos_notify("Grok Loop", f"Error (login may be needed): {e}")
            return True


# =============================================================================
# Tk GUI
# =============================================================================


class GrokLoopApp:
    def __init__(self) -> None:
        ensure_dirs()
        self.root = tk.Tk()
        self.root.title("Grok Cursor Loop")
        self.root.geometry("920x640")
        self.root.configure(bg="#1e1e1e")
        self.root.protocol("WM_DELETE_WINDOW", self.on_quit)

        self.controller = LoopController(self.root, LOG)
        self._build_style()
        self._build_ui()
        self.controller.log_widget = self.log_widget  # type: ignore[attr-defined]
        self.controller.status_label = self.status_label  # type: ignore[attr-defined]

        self.controller.process_cmd_queue()
        self.controller.poll_ui_queue()

        if self.controller.config.auto_launch_loop:
            self.root.after(800, lambda: self.controller.submit_cmd("start"))

        if self.controller.config.start_minimized_to_tray:
            self.root.after(500, self._try_start_minimized_to_tray)

        # macOS: ensure the main window is actually visible and on-screen
        self.root.after(50, self._bring_window_to_front)

        if not STORAGE_STATE_PATH.is_file():
            self.controller.append_log(
                "First run: no saved Grok session yet — a browser window will open for login. "
                "When the chat UI loads, the session is saved to .playwright/grok_storage.json."
            )

    def _build_style(self) -> None:
        """ttk styles for Combobox only; macOS often ignores ttk for the rest — use tk widgets."""
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        bg = "#1e1e1e"
        fg = "#eaeaea"
        entry_bg = "#2d2d2d"
        style.configure("TCombobox", fieldbackground=entry_bg, background=entry_bg, foreground=fg)
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", entry_bg)],
            selectbackground=[("readonly", "#444")],
            selectforeground=[("readonly", fg)],
        )

    def _build_ui(self) -> None:
        cfg = self.controller.config
        pad = {"padx": 8, "pady": 4}
        bg = "#1e1e1e"
        fg = "#eaeaea"
        entry_bg = "#2d2d2d"
        btn_bg = "#3d3d3d"
        btn_fg = "#ffffff"

        # Fill the window: on macOS, ttk Labelframes often paint white; tk.Frame is reliable.
        main = tk.Frame(self.root, bg=bg)
        main.pack(fill=tk.BOTH, expand=True)

        def section(parent: tk.Widget, title: str) -> tk.Frame:
            outer = tk.Frame(
                parent,
                bg=bg,
                highlightbackground="#444444",
                highlightthickness=1,
                padx=8,
                pady=6,
            )
            tk.Label(
                outer,
                text=title,
                bg=bg,
                fg=fg,
                font=("Helvetica", 11, "bold"),
                anchor="w",
            ).pack(fill=tk.X)
            inner = tk.Frame(outer, bg=bg)
            inner.pack(fill=tk.X)
            return inner

        def lbl(parent: tk.Widget, text: str) -> tk.Label:
            return tk.Label(parent, text=text, bg=bg, fg=fg, anchor="w")

        def btn(parent: tk.Widget, text: str, cmd: Callable[[], None]) -> tk.Button:
            return tk.Button(
                parent,
                text=text,
                command=cmd,
                bg=btn_bg,
                fg=btn_fg,
                activebackground="#555555",
                activeforeground=btn_fg,
                relief=tk.FLAT,
                padx=10,
                pady=4,
                highlightthickness=0,
            )

        top_inner = section(main, "Project and loop")
        row0 = tk.Frame(top_inner, bg=bg)
        row0.pack(fill=tk.X)
        lbl(row0, "Project:").pack(side=tk.LEFT)
        self.project_var = tk.StringVar(value=cfg.last_project)
        self.project_combo = ttk.Combobox(
            row0,
            textvariable=self.project_var,
            values=cfg.projects,
            width=26,
            state="normal",
        )
        self.project_combo.pack(side=tk.LEFT, padx=6)

        lbl(row0, "Max iterations:").pack(side=tk.LEFT, padx=(12, 0))
        self.max_iter_var = tk.StringVar(value=str(cfg.max_iterations))
        max_e = tk.Entry(
            row0,
            textvariable=self.max_iter_var,
            width=6,
            bg=entry_bg,
            fg=fg,
            insertbackground=fg,
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground="#555",
        )
        max_e.pack(side=tk.LEFT, padx=4)

        row1 = tk.Frame(top_inner, bg=bg)
        row1.pack(fill=tk.X, pady=(8, 0))
        self.auto_launch_var = tk.BooleanVar(value=cfg.auto_launch_loop)
        tk.Checkbutton(
            row1,
            text="Auto-start loop on launch",
            variable=self.auto_launch_var,
            command=self._save_ui_to_config,
            bg=bg,
            fg=fg,
            activebackground=bg,
            activeforeground=fg,
            selectcolor="#333333",
            highlightthickness=0,
        ).pack(side=tk.LEFT)

        self.min_tray_var = tk.BooleanVar(value=cfg.start_minimized_to_tray)
        tk.Checkbutton(
            row1,
            text="Start minimized to tray",
            variable=self.min_tray_var,
            command=self._save_ui_to_config,
            bg=bg,
            fg=fg,
            activebackground=bg,
            activeforeground=fg,
            selectcolor="#333333",
            highlightthickness=0,
        ).pack(side=tk.LEFT, padx=(16, 0))

        top_outer = row0.master.master
        top_outer.pack(fill=tk.X, **pad)

        row2_inner = section(main, "Notifications and browser")
        r2 = tk.Frame(row2_inner, bg=bg)
        r2.pack(fill=tk.X)
        lbl(r2, "ntfy topic:").pack(side=tk.LEFT)
        self.ntfy_var = tk.StringVar(value=cfg.ntfy_topic)
        tk.Entry(
            r2,
            textvariable=self.ntfy_var,
            width=36,
            bg=entry_bg,
            fg=fg,
            insertbackground=fg,
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground="#555",
        ).pack(side=tk.LEFT, padx=6)

        self.headless_var = tk.BooleanVar(value=cfg.headless)
        tk.Checkbutton(
            r2,
            text="Headless browser (uncheck to watch Chromium)",
            variable=self.headless_var,
            command=self._save_ui_to_config,
            bg=bg,
            fg=fg,
            activebackground=bg,
            activeforeground=fg,
            selectcolor="#333333",
            highlightthickness=0,
        ).pack(side=tk.LEFT, padx=(12, 0))

        r2b = tk.Frame(row2_inner, bg=bg)
        r2b.pack(fill=tk.X, pady=(8, 0))
        self.screenshot_fail_var = tk.BooleanVar(value=cfg.screenshot_on_failure)
        tk.Checkbutton(
            r2b,
            text="Save screenshot on failure (plans/debug/screenshots/)",
            variable=self.screenshot_fail_var,
            command=self._save_ui_to_config,
            bg=bg,
            fg=fg,
            activebackground=bg,
            activeforeground=fg,
            selectcolor="#333333",
            highlightthickness=0,
        ).pack(side=tk.LEFT)

        row2_outer = r2.master.master
        row2_outer.pack(fill=tk.X, **pad)

        btn_inner = section(main, "Actions")
        btn_row = tk.Frame(btn_inner, bg=bg)
        btn_row.pack(fill=tk.X)
        btn(btn_row, "Start Automatic Loop", self.on_start).pack(side=tk.LEFT)
        btn(btn_row, "Stop", self.on_stop).pack(side=tk.LEFT, padx=6)
        btn(btn_row, "Kill Playwright", self.on_kill).pack(side=tk.LEFT)
        btn(btn_row, "Hide to menu bar", self.minimize_to_tray).pack(side=tk.LEFT, padx=12)
        btn_outer = btn_row.master.master
        btn_outer.pack(fill=tk.X, **pad)

        hint = tk.Label(
            main,
            text=(
                "Tip: first run opens a browser for Grok login; your session is saved automatically. "
                "Optional: python3 scripts/smoke_check.py"
            ),
            bg=bg,
            fg="#888888",
            anchor="w",
            wraplength=880,
            justify="left",
            font=("Helvetica", 10),
        )
        hint.pack(fill=tk.X, padx=12, pady=(0, 2))

        self.status_label = tk.Label(
            main,
            textvariable=self.controller.status_var,
            bg=bg,
            fg="#a8a8a8",
            anchor="w",
            font=("Helvetica", 12, "bold"),
        )
        self.status_label.pack(fill=tk.X, padx=10, pady=4)

        pm_outer = tk.Frame(main, bg=bg, highlightbackground="#444444", highlightthickness=1, padx=8, pady=6)
        tk.Label(
            pm_outer,
            text="PM prompt (editable)",
            bg=bg,
            fg=fg,
            font=("Helvetica", 11, "bold"),
            anchor="w",
        ).pack(fill=tk.X)
        self.prompt_text = scrolledtext.ScrolledText(
            pm_outer,
            height=6,
            bg=entry_bg,
            fg=fg,
            insertbackground=fg,
            wrap=tk.WORD,
            highlightthickness=0,
        )
        self.prompt_text.pack(fill=tk.BOTH, expand=True)
        self.prompt_text.insert(tk.END, cfg.pm_prompt)
        pm_outer.pack(fill=tk.BOTH, expand=False, padx=8, pady=4)

        log_outer = tk.Frame(main, bg=bg, highlightbackground="#444444", highlightthickness=1, padx=8, pady=6)
        tk.Label(
            log_outer,
            text="Live log",
            bg=bg,
            fg=fg,
            font=("Helvetica", 11, "bold"),
            anchor="w",
        ).pack(fill=tk.X)
        self.log_widget = scrolledtext.ScrolledText(
            log_outer,
            height=16,
            bg="#111111",
            fg="#c8c8c8",
            insertbackground=fg,
            wrap=tk.WORD,
            state="disabled",
            highlightthickness=0,
        )
        self.log_widget.pack(fill=tk.BOTH, expand=True)
        log_outer.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        self.project_combo.bind("<<ComboboxSelected>>", lambda e: self._save_ui_to_config())
        self.project_combo.bind("<FocusOut>", lambda e: self._sync_project_list())

    def _sync_project_list(self) -> None:
        val = self.project_var.get().strip()
        if not val:
            return
        cfg = self.controller.config
        if val not in cfg.projects:
            cfg.projects.append(val)
        cfg.last_project = val
        self.project_combo["values"] = cfg.projects
        save_config(STATE_JSON_PATH, cfg)

    def _save_ui_to_config(self) -> None:
        cfg = self.controller.config
        cfg.last_project = self.project_var.get().strip() or "default"
        cfg.ntfy_topic = self.ntfy_var.get().strip()
        try:
            cfg.max_iterations = max(1, int(self.max_iter_var.get()))
        except ValueError:
            cfg.max_iterations = 8
        cfg.pm_prompt = self.prompt_text.get("1.0", tk.END).strip() or DEFAULT_PM_PROMPT
        cfg.auto_launch_loop = self.auto_launch_var.get()
        cfg.start_minimized_to_tray = self.min_tray_var.get()
        cfg.headless = self.headless_var.get()
        cfg.screenshot_on_failure = self.screenshot_fail_var.get()
        self._sync_project_list()
        save_config(STATE_JSON_PATH, cfg)

    def on_start(self) -> None:
        self._save_ui_to_config()
        self.project_combo.configure(state="disabled")
        self.controller.submit_cmd("start")

    def on_stop(self) -> None:
        self.controller.submit_cmd("stop")
        self.project_combo.configure(state="normal")

    def on_kill(self) -> None:
        self.controller.submit_cmd("kill")

    def _try_start_minimized_to_tray(self) -> None:
        """Only hide the window if the menu bar icon can be created."""
        if pystray is None or Image is None:
            self.controller.append_log(
                "Start minimized to tray is on, but pystray/Pillow is missing — "
                "keeping the window visible. Install: pip install pystray Pillow"
            )
            try:
                messagebox.showwarning(
                    "Menu bar unavailable",
                    "pystray or Pillow is not installed, so the window cannot be "
                    "hidden to the menu bar. Install:\n  pip install pystray Pillow\n\n"
                    "Uncheck 'Start minimized to tray' to avoid this message.",
                )
            except tk.TclError:
                pass
            return
        self._ensure_tray()
        if getattr(self.controller, "_tray_icon", None):
            self.root.withdraw()

    def _bring_window_to_front(self) -> None:
        try:
            self.root.update_idletasks()
            self.root.lift()
            if sys.platform == "darwin":
                try:
                    self.root.attributes("-topmost", True)
                    self.root.after(
                        150,
                        lambda: self._safe_topmost(False),
                    )
                except tk.TclError:
                    pass
            self.root.focus_force()
        except tk.TclError:
            pass

    def _safe_topmost(self, val: bool) -> None:
        try:
            self.root.attributes("-topmost", val)
        except tk.TclError:
            pass

    def minimize_to_tray(self) -> None:
        if pystray is None or Image is None:
            try:
                messagebox.showwarning(
                    "Menu bar unavailable",
                    "Install pystray and Pillow to use the menu bar icon:\n"
                    "  pip install pystray Pillow",
                )
            except tk.TclError:
                pass
            return
        self._ensure_tray()
        if getattr(self.controller, "_tray_icon", None):
            self.root.withdraw()

    def restore_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _ensure_tray(self) -> None:
        if pystray is None or Image is None:
            self.append_log("pystray/Pillow not installed — cannot use menu bar icon.")
            return
        if getattr(self.controller, "_tray_icon", None):
            return

        def start_tray(*_: Any) -> None:
            self.controller.cmd_queue.put(("start", ()))

        def stop_tray(*_: Any) -> None:
            self.controller.cmd_queue.put(("stop", ()))

        def status_tray(*_: Any) -> None:
            self.controller.cmd_queue.put(("tray_status", ()))

        def restore_tray(*_: Any) -> None:
            self.root.after(0, self.restore_window)

        def quit_tray(*_: Any) -> None:
            self.root.after(0, self.on_quit)

        image = build_tray_image()
        menu = pystray.Menu(
            TrayMenuItem("Show", restore_tray),
            TrayMenuItem("Start loop", start_tray),
            TrayMenuItem("Stop", stop_tray),
            TrayMenuItem("Status", status_tray),
            TrayMenuItem("Quit", quit_tray),
        )
        icon = pystray.Icon("grok_loop", image, "Grok Cursor Loop", menu)
        self.controller._tray_icon = icon

        def run_tray() -> None:
            try:
                icon.run()
            except Exception as e:
                LOG.error("tray: %s", e)

        t = threading.Thread(target=run_tray, daemon=True)
        t.start()

    def append_log(self, s: str) -> None:
        self.controller.append_log(s)

    def on_quit(self) -> None:
        self.controller.submit_cmd("stop")
        self.controller.stop_event.set()
        if self.controller._automation:
            try:
                self.controller._automation.close()
            except Exception:
                pass
        wt = self.controller.worker_thread
        if wt is not None and wt.is_alive():
            wt.join(timeout=12.0)
        if self.controller._tray_icon:
            try:
                self.controller._tray_icon.stop()
            except Exception:
                pass
        self._save_ui_to_config()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def build_tray_image() -> "Image.Image":
    if Image is None or ImageDraw is None:
        raise RuntimeError("Pillow required for tray icon")
    size = 64
    img = Image.new("RGBA", (size, size), (30, 30, 30, 255))
    d = ImageDraw.Draw(img)
    d.ellipse((8, 8, 56, 56), outline=(180, 180, 255, 255), width=3)
    d.text((22, 20), "G", fill=(220, 220, 255, 255))
    return img


def main() -> None:
    if sync_playwright is None:
        print("Install: pip install playwright && playwright install chromium", file=sys.stderr)
        sys.exit(1)
    if Observer is None:
        print("Install: pip install watchdog", file=sys.stderr)
        sys.exit(1)
    app = GrokLoopApp()
    app.run()


if __name__ == "__main__":
    main()
