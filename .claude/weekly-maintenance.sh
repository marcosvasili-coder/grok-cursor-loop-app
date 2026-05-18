#!/usr/bin/env bash
# Auto-generated — runs every Monday 09:00
export PATH="/Users/marcosvasili/.grok/bin:/Users/marcosvasili/Library/Application Support/reflex/bun/bin:/Users/marcosvasili/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/local/sbin:/opt/homebrew/bin:/opt/homebrew/sbin:/System/Cryptexes/App/usr/bin:/usr/bin:/bin:/usr/sbin:/sbin:/var/run/com.apple.security.cryptexd/codex.system/bootstrap/usr/local/bin:/var/run/com.apple.security.cryptexd/codex.system/bootstrap/usr/bin:/var/run/com.apple.security.cryptexd/codex.system/bootstrap/usr/appleinternal/bin:/pkg/env/global/bin:/opt/X11/bin:/Library/Apple/usr/bin:/Applications/Cursor.app/Contents/Resources/app/resources/helpers:/Users/marcosvasili/.grok/bin:/Users/marcosvasili/Library/Application Support/reflex/bun/bin:/Users/marcosvasili/.local/bin:/Users/marcosvasili/.lmstudio/bin:/Users/marcosvasili/.lmstudio/bin"

REPO="/Volumes/External SSD/dev/grok-cursor-loop-app"
LOG="/Volumes/External SSD/dev/grok-cursor-loop-app/.claude/setup-log.txt"

cd "$REPO" || exit 1
echo "" >> "$LOG"
echo "=== Weekly Maintenance: $(date) ===" >> "$LOG"

# Step 1: health report
claude -p 'Read ALL context files:
- CLAUDE.md, CLAUDE.local.md
- All files under .claude/skills/
- All files under .claude/agents/
- All files under .cursor/rules/
- All files under .cursor/agents/

Scan the codebase for drift vs the rules.
Save a health report to .claude/weekly-review.md:

## Stale Rules
References to files, commands, or patterns no longer in the repo.

## Bloat
Any context file over 200 lines.

## Conflicts
New contradictions since last review.

## Missing Coverage
New code areas with no rule or skill coverage.

## Recommended Fixes
Prioritised. File, section, exact change per item.

End with: Last reviewed: [current date]'   --model sonnet   --permission-mode auto   --allowedTools "Read,Write,Glob,Grep"   --max-turns 15   >> "$LOG" 2>&1

# Step 2: auto-apply fixes
claude -p 'Read .claude/weekly-review.md.
Apply every fix under Recommended Fixes in priority order.
Remove stale rules, trim bloat, resolve conflicts, fill gaps.
Only make changes grounded in the actual repo.
Never modify runner.mdc, the runner skill, cursor-agent-cli-workflow.mdc, or agent frontmatter.
Append to .claude/weekly-review.md:
## Auto-Applied Fixes
Date: [date]
[list of changes]'   --model sonnet   --permission-mode auto   --allowedTools "Read,Write,Edit,Glob,Grep"   --max-turns 20   >> "$LOG" 2>&1

# Step 3: commit context changes
git add CLAUDE.md .claude/skills/ .cursor/rules/ 2>/dev/null || true
if ! git diff --cached --quiet 2>/dev/null; then
  git commit -m "chore: weekly AI context maintenance — $(date +%Y-%m-%d)" >> "$LOG" 2>&1
fi

# Notify Hermes with weekly review summary
if command -v hermes &>/dev/null; then
  hermes chat -z "Read $(pwd)/.claude/weekly-review.md and send me a Telegram summary of any issues found. If nothing needs attention say 'All clear: $(basename $(pwd))'. Keep it to bullet points."
fi

echo "Done: $(date)" >> "$LOG"
