# Changelog

## 1.0.1 - 2026-11-13

- README: added the line that this tool is not affiliated with, endorsed by or sponsored by Anthropic.
- The package is now named `handoff-check`.
- No change to behaviour. Same tests.

## 1.0.0 - 2026-11-12

First release.

- Reads a report from a file or standard input and extracts file paths, URLs, e-mail addresses and delivery wording (English and Korean).
- Sorts every claim into `prepared`, `sent`, `landed`, `unverified` or `missing`.
- `landed` is only ever said about local files. External delivery without evidence stays `unverified`.
- `--evidence FILE` marks a destination as `sent` when your own log mentions it.
- `--strict` fails on unverified delivery claims.
- No absolute paths in the output unless `--show-absolute` is given.
- Paths with spaces and non-ASCII names in backticks, quotes and Markdown links.
- 42 unit tests.
