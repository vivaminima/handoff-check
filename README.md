# handoff-check
Unlike a plain Stop-hook reminder, this checks the claimed artifact and writes an explicit verification receipt.

Agents say "done, I sent it" when all they did was write a local file. This tool reads the agent's report, pulls out the file paths and delivery claims, checks them against the disk, and sorts every claim into a group you can read in five seconds.

```
$ python3 handoff_check.py report.md

Handoff check 1.0.1
Report: report.md

PREPARED  (file exists here; the same line claims a delivery)
  L4    dist/app-1.2.zip  [48211 bytes]

SENT  (your evidence log mentions it; arrival is not proven)
  (none)

LANDED  (local file is where the report says)
  L3    docs/release-notes.md  [1904 bytes]

UNVERIFIED  (delivery claimed, no evidence given)
  L4    https://example.com/releases/1.2
  L6    "Emailed the summary to the client."  [no destination named]

MISSING  (the report names a file that is not there)
  L5    CHANGELOG.md

Summary: prepared 1, sent 0, landed 1, unverified 2, missing 1
Result: FAIL (1 claimed file(s) missing)
Limit: this tool works offline. It cannot prove that anything arrived in an external inbox, channel or server.
```

- Python 3.8 or newer, standard library only, one file.
- Makes no network requests. Writes no files.
- MIT licence.

## What this tool cannot do

**An offline tool cannot prove that anything arrived in an external inbox, channel or server.** This one does not try, and it never prints "landed" for anything outside your disk.

- `landed` is only ever said about a **local file** that is at the path the report names.
- `sent` means only this: a log file **you** supplied mentions the destination. It is evidence that a send was attempted from your side. It is not proof of arrival.
- Everything else that claims a delivery is `unverified`. Treat it as "not checked", not as "probably fine".

If you need proof of arrival, look in the place it was supposed to arrive.

## The five groups

| Group | Meaning | Fails the check? |
| --- | --- | --- |
| `prepared` | The file exists locally, and the same line claims it was sent, uploaded, pushed, and so on. The file is ready; whether it left is unknown. | No |
| `sent` | A destination (URL, e-mail address) or a file name on a delivery line appears in an evidence log you passed with `--evidence`. | No |
| `landed` | A local file or folder is where the report says it is. Shown as landed (local). | No |
| `unverified` | A delivery is claimed and there is no evidence. | Only with `--strict` |
| `missing` | The report names a file that does not exist. | Yes |

Exit codes: `0` pass, `1` fail, `2` the report or an evidence file could not be read.

## Use

```
python3 handoff_check.py report.md
python3 handoff_check.py report.md --root path/to/project
python3 handoff_check.py report.md --evidence push.log --evidence mail.log --strict
some-command-that-prints-the-report | python3 handoff_check.py
```

| Option | Meaning |
| --- | --- |
| `report` | The report file. Leave it out, or use `-`, to read from standard input. |
| `--root DIR` | Folder that relative paths in the report are read from. Default: the current folder. |
| `--evidence FILE` | A local log that proves a send (saved command output, a mail log). May be repeated. |
| `--strict` | Exit 1 for unverified delivery claims too. |
| `--show-absolute` | Print absolute paths. Off by default. |

## What it finds in a report

- Paths in backticks, in double or single quotes, in Markdown links, and bare in the text: `` `dist/app.zip` ``, `"my docs/final report.docx"`, `[notes](docs/notes.md)`, `src/app.py:42`.
- Paths with spaces and non-ASCII names, when they are in backticks or quotes: `` `결과 폴더/최종 보고서.md` ``.
- URLs, e-mail addresses and `host.tld/path` strings, as destinations.
- Delivery wording in English and Korean (sent, emailed, pushed, uploaded, posted, published, deployed, delivered, submitted, shared, forwarded, released, shipped, handed off, 보냈, 전송, 업로드, 배포, ...). A line with such wording and no destination is listed as one unverified claim.

Fenced code blocks are skipped. A bare word counts as a file only when it has a path separator plus an extension, starts with `./`, `../`, `~/` or a drive letter, or ends in a common file extension. So `and/or`, `Node.js`, `v1.2.3`, `os.path.join` and `/help` are left alone.

## No absolute paths in the output

By default the output never contains an absolute path. Paths inside `--root` are printed relative to it. Paths outside it are printed as `<outside root>/name.ext`. A report given by absolute path is printed by file name only. `--show-absolute` turns this off.

## Tests

```
python3 -m unittest discover -s tests -v
```

42 tests. They cover: an existing file is landed (local), a missing file fails, a URL alone is unverified, Korean names and spaces, no absolute paths in the default output, evidence logs, false positives, a cp949 console.

## Known limits

- Extraction is pattern-based. A path with spaces that is not in backticks or quotes is not seen as one path. An unusual file extension with no folder in front of it is not seen as a file.
- A report can name a file that already existed before the session. The free version checks that it exists, not that it is new or correct. Size is shown, and empty files are flagged.
- Tested on Windows with Python 3.10.

## Pro version

**Handoff Check Pro** by Vivaminima adds: rules ("when the report says released, `dist/*.zip` and `CHANGELOG.md` must exist"), content checks (required phrases, SHA-256, minimum size, maximum age), a JSON receipt for CI and handoff logs, and a Claude Code Stop hook mode with examples.

## Not affiliated

This tool works with Claude Code. It is not affiliated with, endorsed by or sponsored by Anthropic.

## Licence

MIT. See [LICENSE](LICENSE). Copyright (c) 2026 Vivaminima.

## More from Vivaminima

- **Handoff Check Pro ($19)**, the paid edition of this tool, one-time payment on Gumroad: https://vivastory4.gumroad.com/l/handoff-check-pro
- **Token Audit Kit ($19)** — see how many tokens your CLAUDE.md and its @imports cost before your first prompt, and a step-by-step guide to split it. Free script: https://github.com/vivaminima/context-file-audit · Paid kit: https://vivaminima.lemonsqueezy.com/checkout/buy/57973270-94ea-4cc7-bcb4-294693714087
- Free tools: [skill-audit-kit](https://github.com/vivaminima/skill-audit-kit) · [secret-map](https://github.com/vivaminima/secret-map) · [inbox-ledger](https://github.com/vivaminima/inbox-ledger) · [release-gate](https://github.com/vivaminima/release-gate) · [skill-install-gate](https://github.com/vivaminima/skill-install-gate) · [console-safe](https://github.com/vivaminima/console-safe) · [checklist-stop](https://github.com/vivaminima/checklist-stop) · [handoff-check](https://github.com/vivaminima/handoff-check) · [llm-budget-router-lite](https://github.com/vivaminima/llm-budget-router-lite) · [go-no-go-verdict-skill](https://github.com/vivaminima/go-no-go-verdict-skill) · [ai-company-starter-kit](https://github.com/vivaminima/ai-company-starter-kit) · [beginner-readme-section](https://github.com/vivaminima/beginner-readme-section)

Vivaminima is not affiliated with, endorsed by or sponsored by Anthropic.
