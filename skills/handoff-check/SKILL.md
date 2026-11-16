---
name: handoff-check
description: Checks a "done, I sent it" report against the disk: every path the report names must exist, and claims without evidence are flagged. Use when the user asks, for example, "check this report against the files", "did it really land", "handoff check", "보고서가 사실인지 확인해 줘".
---

# handoff-check

Checks a "done, I sent it" report against the disk: every path the report names must exist, and claims without evidence are flagged. A small Python tool shipped in this plugin: standard library only, nothing to install, runs locally.

## Run

Use `python` (Windows: `py -3` also works; macOS/Linux: `python3`). On Windows add `-X utf8` if the console shows broken characters.

    python "${CLAUDE_PLUGIN_ROOT}/handoff_check.py" <report.md> --root <project-folder>
    python "${CLAUDE_PLUGIN_ROOT}/handoff_check.py" <report.md> --evidence <push.log> --strict

Run it from the user's project folder and pass the path they mean. If no path is given, ask which folder or file to check.

## Read the result

Say which claims are confirmed, which are missing on disk and which have no evidence.

Show the tool's own output (shortened if long) and then a two- or three-line summary. Do not change the user's files unless they ask.
