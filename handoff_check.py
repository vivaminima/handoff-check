#!/usr/bin/env python3
"""handoff-check

Reads an agent's "done / sent" report, pulls out the file paths and delivery
claims in it, and checks them against the disk. Every claim ends up in one
of five groups:

  prepared    the file exists here, on a line that says it went somewhere else
  sent        your own evidence log mentions the destination
  landed      the file is at the local path the report names
  unverified  delivery is claimed and there is no evidence for it
  missing     the report names a file that is not there

This tool works offline. It cannot prove that anything arrived in an
external inbox, channel or server, and it never says so.

Standard library only. Makes no network requests. Writes no files.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from urllib.parse import unquote

__version__ = "1.0.1"

LIMIT_NOTE = ("Limit: this tool works offline. It cannot prove that anything "
              "arrived in an external inbox, channel or server.")

STATUSES = ("prepared", "sent", "landed", "unverified", "missing")
_SECTION_HELP = {
    "prepared": "file exists here; the same line claims a delivery",
    "sent": "your evidence log mentions it; arrival is not proven",
    "landed": "local file is where the report says",
    "unverified": "delivery claimed, no evidence given",
    "missing": "the report names a file that is not there",
}

KNOWN_EXT = frozenset("""
md markdown txt rst json jsonl yaml yml toml ini cfg conf csv tsv xml html htm
css js mjs cjs ts tsx jsx py pyi ipynb rb go rs java kt swift c h cpp hpp cs
php sh bash zsh ps1 bat cmd sql log lock zip tar gz tgz bz2 xz 7z whl jar pdf
doc docx xls xlsx ppt pptx png jpg jpeg gif svg webp ico bmp mp3 wav mp4 mov
webm patch diff exe dll bin dat db sqlite
""".split())

_NOT_FILES = frozenset("""
node.js next.js vue.js nuxt.js express.js three.js d3.js react.js
""".split())

_COMMAND_WORDS = frozenset("""
python python3 py pip pip3 uv npm npx node yarn pnpm git gh cp mv cat ls cd rm
mkdir bash sh zsh pwsh powershell make cargo go docker zip unzip tar pytest
echo type copy move dir del
""".split())

_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
_MDLINK_RE = re.compile(r"(\[[^\]\n]*\])\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"\n]*\")?\s*\)")
_URL_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]+://[^\s<>\"'`)\]]+")
_EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_BACKTICK_RE = re.compile(r"`([^`\n]+)`")
_DQUOTE_RE = re.compile(r"\"([^\"\n]+)\"|“([^”\n]+)”")
_SQUOTE_RE = re.compile(r"(?<!\w)'([^'\n]+)'(?!\w)")
_LINE_SUFFIX_RE = re.compile(r"^(.*\.[A-Za-z0-9]{1,8}):\d+(?::\d+)?$")
_HANGUL_TAIL_RE = re.compile(r"^(.*\.[A-Za-z0-9]{1,8})[가-힣]+$")
_EXT_RE = re.compile(r"\.([A-Za-z0-9]{1,8})$")
_ANCHOR_RE = re.compile(r"^(\.{1,2}[\\/]|~[\\/]|[A-Za-z]:[\\/]|\\\\)")
_ABS_CLAIM_RE = re.compile(r"^([A-Za-z]:[\\/]|[\\/]|~)")
_DOMAIN_RE = re.compile(
    r"^[\w-]+(?:\.[\w-]+)*\.(?:com|org|net|io|dev|app|ai|co|kr|me|sh|gg|xyz|edu|gov)$",
    re.IGNORECASE,
)
_DELIVERY_WORDS = (
    r"\b(?:sent|e-?mailed|mailed|pushed|uploaded|posted|published|deployed|"
    r"delivered|submitted|shared|forwarded|released|shipped|"
    r"handed\s+(?:off|over))\b"
    r"|보냈|보냄|보내\s?드렸|전송|발송|전달|올렸|올림|업로드|게시|푸시|배포|제출|공유"
)


def delivery_regex(extra_words=()):
    """Regex for wording that claims something left this machine."""
    pattern = _DELIVERY_WORDS
    extra = [re.escape(word) for word in extra_words if word]
    if extra:
        pattern += "|" + "|".join(extra)
    return re.compile(pattern, re.IGNORECASE)


# ------------------------------------------------------------ extraction

def _clean_url(url):
    return url.rstrip(".,;:!?")


def looks_like_path(text, quoted):
    """Decide whether a piece of report text is meant as a file path."""
    if not text or len(text) > 260 or "\n" in text:
        return False
    if any(char in text for char in "*?<>|{}$") or "://" in text or "@" in text:
        return False
    has_sep = "/" in text or "\\" in text
    base = re.split(r"[\\/]", text.rstrip("/\\"))[-1]
    if not base or base.lower() in _NOT_FILES:
        return False
    match = _EXT_RE.search(base)
    ext = match.group(1).lower() if match else ""
    has_ext = bool(ext) and bool(re.search(r"[a-z]", ext))
    if not has_sep:
        return ext in KNOWN_EXT and base != "." + ext
    if text.startswith("/") and not text.startswith("//"):
        segments = [part for part in text.split("/") if part]
        return has_ext or len(segments) >= 2
    if quoted:
        return True
    return has_ext or bool(_ANCHOR_RE.match(text))


def _strip_token(token):
    token = token.lstrip("([{<\"'*").rstrip(")]}>\"'*,;:!?.")
    match = _HANGUL_TAIL_RE.match(token)
    if match:
        token = match.group(1)
    match = _LINE_SUFFIX_RE.match(token)
    if match:
        token = match.group(1)
    return token


def _is_domain_path(text):
    head = text.split("/", 1)[0]
    return "/" in text and bool(_DOMAIN_RE.match(head))


class LineClaims(object):
    __slots__ = ("line", "text", "paths", "dests", "delivery")

    def __init__(self, line, text):
        self.line = line
        self.text = text
        self.paths = []
        self.dests = []
        self.delivery = False


def extract(text, exists=None, extra_delivery_words=()):
    """Pull path and delivery claims out of a report, line by line.

    `exists` is a callback (raw path -> bool) used only to tell a quoted
    path with spaces from a quoted sentence.
    """
    exists = exists or (lambda raw: False)
    delivery_re = delivery_regex(extra_delivery_words)
    records = []
    fence = ""

    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if fence:
            if (stripped and stripped[0] == fence[0] and len(stripped) >= len(fence)
                    and stripped == stripped[0] * len(stripped)):
                fence = ""
            continue
        match = _FENCE_RE.match(line)
        if match:
            fence = match.group(1)
            continue
        if not stripped:
            continue

        record = LineClaims(number, stripped)

        def add_path(raw):
            if raw and raw not in record.paths:
                record.paths.append(raw)

        def add_dest(raw):
            if raw and raw not in record.dests:
                record.dests.append(raw)

        def bare(token):
            token = _strip_token(token)
            if _is_domain_path(token):
                add_dest(token)
            elif looks_like_path(token, quoted=False):
                add_path(token)

        def span(raw):
            raw = raw.strip()
            match = _LINE_SUFFIX_RE.match(raw)
            if match:
                raw = match.group(1)
            if not raw:
                return
            if _is_domain_path(raw) and " " not in raw:
                add_dest(raw)
                return
            if " " not in raw:
                if looks_like_path(raw, quoted=True):
                    add_path(raw)
                return
            if exists(raw):
                add_path(raw)
                return
            words = raw.split()
            is_command = (words[0].lower() in _COMMAND_WORDS
                          or any(word.startswith("-") for word in words[1:]))
            tokens = [t for t in (_strip_token(w) for w in words)
                      if looks_like_path(t, quoted=False)]
            if is_command:
                tokens = [t for t in tokens if t != _strip_token(words[0])]
            whole_ok = (not is_command and len(words) <= 4
                        and looks_like_path(raw, quoted=True))
            if whole_ok and not any(exists(t) for t in tokens):
                add_path(raw)
            else:
                for token in tokens:
                    add_path(token)

        def link(match):
            target = match.group(2)
            if _URL_RE.match(target) or target.lower().startswith("mailto:"):
                add_dest(_clean_url(target))
            else:
                target = unquote(target.split("#", 1)[0])
                if target and looks_like_path(target, quoted=True):
                    add_path(target)
            return match.group(1) + " "

        def url(match):
            add_dest(_clean_url(match.group()))
            return " "

        def quoted(match):
            span(next(group for group in match.groups() if group is not None))
            return " "

        work = _MDLINK_RE.sub(link, line)
        work = _URL_RE.sub(url, work)
        work = _EMAIL_RE.sub(url, work)
        work = _BACKTICK_RE.sub(quoted, work)
        work = _DQUOTE_RE.sub(quoted, work)
        work = _SQUOTE_RE.sub(quoted, work)
        for token in work.split():
            bare(token)

        record.delivery = bool(record.dests) or bool(delivery_re.search(line))
        if record.paths or record.dests or record.delivery:
            records.append(record)
    return records


# -------------------------------------------------------------- checking

def resolve_path(raw, root):
    """Absolute path for a claimed path; relative claims are read from root."""
    if raw.startswith("~"):
        raw = os.path.expanduser(raw)
    if _ABS_CLAIM_RE.match(raw):
        return os.path.abspath(raw)
    return os.path.normpath(os.path.join(root, raw))


def display_path(raw, absolute, root, show_absolute=False):
    """How a path is printed. No absolute paths unless asked for."""
    if show_absolute:
        return absolute
    if not _ABS_CLAIM_RE.match(raw):
        return os.path.normpath(raw).replace("\\", "/")
    try:
        relative = os.path.relpath(absolute, root)
    except ValueError:
        relative = ".."
    if not relative.startswith(".."):
        return relative.replace("\\", "/")
    return "<outside root>/" + os.path.basename(absolute.rstrip("/\\"))


def _shorten(text, width=70):
    text = " ".join(text.split())
    return text if len(text) <= width else text[:width - 3] + "..."


def analyze(text, root, evidence_texts=(), extra_delivery_words=(),
            show_absolute=False):
    """Check every claim in the report. Returns a list of item dicts.

    Item keys: line, kind (file / destination / claim), target, status,
    notes, and for files "path" (absolute, for further checks; never printed
    unless show_absolute is on).
    """
    root = os.path.abspath(root)

    def exists(raw):
        return os.path.exists(resolve_path(raw, root))

    items = []
    by_path = {}
    seen_dests = set()

    for record in extract(text, exists, extra_delivery_words):
        for raw in record.paths:
            absolute = resolve_path(raw, root)
            key = os.path.normcase(absolute)
            known = by_path.get(key)
            if known is not None:
                if record.delivery and known["status"] == "landed":
                    known["status"] = "prepared"
                    known["notes"].append("delivery claimed on line %d" % record.line)
                continue
            item = {"line": record.line, "kind": "file", "path": absolute,
                    "target": display_path(raw, absolute, root, show_absolute),
                    "status": "missing", "notes": []}
            if os.path.isdir(absolute):
                item["status"] = "prepared" if record.delivery else "landed"
                item["notes"].append("folder")
            elif os.path.isfile(absolute):
                item["status"] = "prepared" if record.delivery else "landed"
                size = os.path.getsize(absolute)
                item["notes"].append("empty file, 0 bytes" if size == 0
                                     else "%d bytes" % size)
            by_path[key] = item
            items.append(item)

        for dest in record.dests:
            if dest in seen_dests:
                continue
            seen_dests.add(dest)
            proven = any(dest in evidence for evidence in evidence_texts)
            items.append({"line": record.line, "kind": "destination",
                          "target": dest,
                          "status": "sent" if proven else "unverified",
                          "notes": ["found in evidence"] if proven else []})

        if record.delivery and not record.dests:
            names = [os.path.basename(raw.rstrip("/\\")) for raw in record.paths]
            proven = any(name and name in evidence
                         for name in names for evidence in evidence_texts)
            items.append({"line": record.line, "kind": "claim",
                          "target": '"%s"' % _shorten(record.text),
                          "status": "sent" if proven else "unverified",
                          "notes": ["file name found in evidence"] if proven
                          else ["no destination named"]})
    return items


def verdict(items, strict=False):
    """(label, exit code) for a list of checked items."""
    counts = count_statuses(items)
    if counts["missing"]:
        return "FAIL (%d claimed file(s) missing)" % counts["missing"], 1
    if counts["unverified"]:
        if strict:
            return ("FAIL (%d delivery claim(s) without evidence, --strict)"
                    % counts["unverified"]), 1
        return ("PASS with %d unverified delivery claim(s)"
                % counts["unverified"]), 0
    if not items:
        return "PASS (no file or delivery claims found)", 0
    return "PASS", 0


def count_statuses(items):
    counts = dict((status, 0) for status in STATUSES)
    for item in items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return counts


def render_text(items, report_name, strict=False, statuses=STATUSES,
                help_text=None, result=None):
    """The plain-text report."""
    help_text = help_text or _SECTION_HELP
    lines = ["Handoff check %s" % __version__, "Report: %s" % report_name, ""]
    for status in statuses:
        lines.append("%s  (%s)" % (status.upper(), help_text[status]))
        group = [item for item in items if item["status"] == status]
        if not group:
            lines.append("  (none)")
        for item in group:
            note = "  [%s]" % "; ".join(item["notes"]) if item["notes"] else ""
            where = "L%d" % item["line"] if item["line"] else "rule"
            lines.append("  %-5s %s%s" % (where, item["target"], note))
        lines.append("")
    counts = count_statuses(items)
    lines.append("Summary: " + ", ".join("%s %d" % (s, counts.get(s, 0)) for s in statuses))
    lines.append("Result: " + (result or verdict(items, strict)[0]))
    lines.append(LIMIT_NOTE)
    return "\n".join(lines)


# ------------------------------------------------------------------- cli

def harden_streams():
    """Never crash on a console that cannot print a character (cp949, cp1252)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except Exception:
            pass


def decode(raw):
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    return raw.decode("utf-8-sig", errors="replace")


def read_file(path):
    with open(path, "rb") as handle:
        return decode(handle.read())


def report_label(path):
    """Name printed for the report file: never an absolute path."""
    if not path or path == "-":
        return "<stdin>"
    if _ABS_CLAIM_RE.match(path):
        return os.path.basename(path)
    return os.path.normpath(path).replace("\\", "/")


def read_report(path):
    """Return the report text, or raise OSError / ValueError with a reason."""
    if not path or path == "-":
        if sys.stdin is None or sys.stdin.isatty():
            raise ValueError("give a report file, or pipe the report in")
        return decode(sys.stdin.buffer.read())
    return read_file(path)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="handoff_check.py",
        description="Check the files and delivery claims in an agent's "
                    "handoff report against the disk. Offline.",
    )
    parser.add_argument("report", nargs="?", help="report file; omit or use - "
                        "to read the report from standard input")
    parser.add_argument("--root", default=".", help="folder that relative "
                        "paths in the report are read from (default: here)")
    parser.add_argument("--evidence", action="append", default=[], metavar="FILE",
                        help="a local log that proves a send (command output, "
                             "mail log); may be given more than once")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 for unverified delivery claims too")
    parser.add_argument("--show-absolute", action="store_true",
                        help="print absolute paths (off by default)")
    parser.add_argument("--version", action="version",
                        version="handoff-check " + __version__)
    return parser


def load_evidence(paths):
    return [read_file(path) for path in paths]


def main(argv=None):
    harden_streams()
    args = build_parser().parse_args(argv)
    try:
        text = read_report(args.report)
        evidence = load_evidence(args.evidence)
    except (OSError, ValueError) as exc:
        reason = exc.strerror if isinstance(exc, OSError) and exc.strerror else str(exc)
        sys.stderr.write("handoff-check: cannot read input: %s\n" % reason)
        return 2
    if not os.path.isdir(args.root):
        sys.stderr.write("handoff-check: --root is not a folder\n")
        return 2
    items = analyze(text, args.root, evidence, show_absolute=args.show_absolute)
    print(render_text(items, report_label(args.report), args.strict))
    return verdict(items, args.strict)[1]


if __name__ == "__main__":
    sys.exit(main())
