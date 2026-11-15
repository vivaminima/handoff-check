"""Tests for handoff_check.py. Run: python -m unittest discover -s tests -v"""
import locale
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.dirname(HERE)
SCRIPT = os.path.join(PACKAGE, "handoff_check.py")
sys.path.insert(0, PACKAGE)

import handoff_check as hc  # noqa: E402

ABSOLUTE_RE = re.compile(r"[A-Za-z]:[\\/]|/Users/|/home/|/tmp/|/var/")


class Case(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="hoc test "))
        self.addCleanup(shutil.rmtree, self.root, True)

    def write(self, name, text="content\n"):
        path = os.path.join(self.root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        return path

    def run_script(self, report_text, args=(), env=None, stdin=False):
        environ = dict(os.environ)
        for name in ("PYTHONIOENCODING", "PYTHONUTF8"):
            environ.pop(name, None)
        if sys.flags.utf8_mode:  # keep the child in the same mode as this process
            environ["PYTHONUTF8"] = "1"
        environ.update(env or {})
        command = [sys.executable, SCRIPT]
        data = None
        if stdin:
            data = report_text.encode("utf-8")
        else:
            self.write("report.md", report_text)
            command.append("report.md")
        proc = subprocess.run(command + list(args), input=data,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              cwd=self.root, env=environ)
        encoding = environ.get("PYTHONIOENCODING") or locale.getpreferredencoding(False)
        return (proc.returncode, proc.stdout.decode(encoding, "replace"),
                proc.stderr.decode(encoding, "replace"))

    def statuses(self, text, **kwargs):
        items = hc.analyze(text, self.root, **kwargs)
        return [(item["target"], item["status"]) for item in items]

    def section(self, out, name):
        """Lines printed under one heading of the text report."""
        lines = out.splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith(name + "  ("))
        body = []
        for line in lines[start + 1:]:
            if not line.strip():
                break
            body.append(line.strip())
        return body


class CoreStatuses(Case):
    def test_existing_file_is_landed_locally(self):
        self.write("out/notes.md")
        code, out, err = self.run_script("Wrote the notes to out/notes.md.\n")
        self.assertEqual(code, 0)
        self.assertEqual(self.section(out, "LANDED"), ["L1    out/notes.md  [8 bytes]"])
        self.assertIn("Result: PASS", out)

    def test_missing_file_fails(self):
        code, out, err = self.run_script("Saved the build as `dist/app.zip`.\n")
        self.assertEqual(code, 1)
        self.assertEqual(self.section(out, "MISSING"), ["L1    dist/app.zip"])
        self.assertIn("Result: FAIL (1 claimed file(s) missing)", out)

    def test_url_only_is_unverified(self):
        code, out, err = self.run_script("It is live at https://example.com/post/1.\n")
        self.assertEqual(code, 0)
        self.assertEqual(self.section(out, "UNVERIFIED"), ["L1    https://example.com/post/1"])
        self.assertIn("PASS with 1 unverified delivery claim(s)", out)

    def test_strict_fails_on_unverified(self):
        code, out, err = self.run_script("See https://example.com/x\n", ["--strict"])
        self.assertEqual(code, 1)
        self.assertIn("without evidence, --strict", out)

    def test_file_on_a_delivery_line_is_only_prepared(self):
        self.write("dist/app.zip")
        got = self.statuses("Uploaded `dist/app.zip` to the release page.")
        self.assertEqual(got[0], ("dist/app.zip", "prepared"))
        self.assertEqual(got[1][1], "unverified")
        self.assertEqual(len(got), 2)

    def test_evidence_turns_a_destination_into_sent(self):
        self.write("dist/app.zip")
        text = "Uploaded dist/app.zip to https://example.com/releases/7"
        self.assertEqual(self.statuses(text), [
            ("dist/app.zip", "prepared"),
            ("https://example.com/releases/7", "unverified")])
        log = "upload ok -> https://example.com/releases/7 (200)"
        self.assertEqual(self.statuses(text, evidence_texts=[log]), [
            ("dist/app.zip", "prepared"),
            ("https://example.com/releases/7", "sent")])

    def test_evidence_by_file_name_when_no_destination_is_named(self):
        self.write("dist/app.zip")
        got = self.statuses("Pushed dist/app.zip.", evidence_texts=["sent app.zip ok"])
        self.assertEqual([status for _, status in got], ["prepared", "sent"])

    def test_evidence_option(self):
        self.write("send.log", "delivered to dev@example.com\n")
        code, out, err = self.run_script("Emailed the summary to dev@example.com.\n",
                                         ["--evidence", "send.log", "--strict"])
        self.assertEqual(code, 0)
        self.assertEqual(self.section(out, "SENT"),
                         ["L1    dev@example.com  [found in evidence]"])

    def test_nothing_is_ever_landed_remotely(self):
        got = self.statuses("Posted to https://example.com/a and mailed b@example.com",
                            evidence_texts=["https://example.com/a b@example.com"])
        self.assertEqual(set(status for _, status in got), {"sent"})

    def test_delivery_wording_without_any_target(self):
        got = self.statuses("I sent the report to the client.")
        self.assertEqual(got, [('"I sent the report to the client."', "unverified")])

    def test_korean_delivery_wording(self):
        self.write("보고서.md")
        got = self.statuses("보고서.md를 고객에게 보냈습니다.")
        self.assertEqual([status for _, status in got], ["prepared", "unverified"])
        self.assertEqual(got[0][0], "보고서.md")

    def test_later_delivery_line_downgrades_landed(self):
        self.write("a.md")
        got = self.statuses("Wrote a.md.\nThen uploaded a.md.")
        self.assertEqual(got[0], ("a.md", "prepared"))

    def test_no_claims(self):
        code, out, err = self.run_script("All good, nothing to add.\n")
        self.assertEqual(code, 0)
        self.assertIn("PASS (no file or delivery claims found)", out)

    def test_limit_note_is_always_printed(self):
        for text in ("nothing\n", "Wrote missing.md\n", "see https://example.com\n"):
            self.assertIn("cannot prove that anything arrived", self.run_script(text)[1])

    def test_all_five_headings_are_always_printed(self):
        out = self.run_script("nothing\n")[1]
        for name in ("PREPARED", "SENT", "LANDED", "UNVERIFIED", "MISSING"):
            self.assertEqual(self.section(out, name), ["(none)"])


class PathExtraction(Case):
    def test_korean_and_spaces(self):
        self.write("결과 폴더/최종 보고서.md")
        self.write("my docs/final report.docx")
        text = ('Saved `결과 폴더/최종 보고서.md` and "my docs/final report.docx" '
                "and '없는 폴더/빠진 파일.txt'.")
        self.assertEqual(self.statuses(text), [
            ("결과 폴더/최종 보고서.md", "landed"),
            ("my docs/final report.docx", "landed"),
            ("없는 폴더/빠진 파일.txt", "missing")])

    def test_korean_output_on_cli(self):
        self.write("결과 폴더/최종 보고서.md")
        code, out, err = self.run_script("`결과 폴더/최종 보고서.md` 를 만들었다.\n")
        self.assertEqual(code, 0)
        self.assertIn("결과 폴더/최종 보고서.md", out)

    def test_korean_particle_after_file_name(self):
        self.write("report.md")
        self.assertEqual(self.statuses("report.md를 만들고 summary.txt도 썼다."), [
            ("report.md", "landed"), ("summary.txt", "missing")])

    def test_markdown_links(self):
        self.write("docs/guide.md")
        self.write("my file.txt")
        text = ("See [the guide](docs/guide.md#usage), [spaced](my%20file.txt), "
                "[gone](docs/none.md) and [site](https://example.com/x).")
        self.assertEqual(self.statuses(text), [
            ("docs/guide.md", "prepared"), ("my file.txt", "prepared"),
            ("docs/none.md", "missing"), ("https://example.com/x", "unverified")])

    def test_line_number_suffix(self):
        self.write("src/app.py")
        self.assertEqual(self.statuses("Fixed the bug in src/app.py:42 and `src/app.py:7:3`."),
                         [("src/app.py", "landed")])

    def test_wrapping_punctuation(self):
        self.write("a.md")
        self.write("b.json")
        self.assertEqual(self.statuses("Files: **a.md**, (b.json). Also c.yaml!"), [
            ("a.md", "landed"), ("b.json", "landed"), ("c.yaml", "missing")])

    def test_commands_in_backticks(self):
        self.write("build.py")
        self.write("tests/test_x.py")
        text = "Ran `python build.py` and `python -m unittest tests/test_x.py -v`."
        self.assertEqual(self.statuses(text), [
            ("build.py", "landed"), ("tests/test_x.py", "landed")])

    def test_quoted_sentence_that_ends_in_a_file_name(self):
        self.write("config.json")
        self.assertEqual(self.statuses('The note says "we updated config.json" today.'),
                         [("config.json", "landed")])

    def test_code_blocks_are_skipped(self):
        text = "Done.\n```\ncp gone.txt other.txt\n```\n~~~\nmissing.md\n~~~\n"
        self.assertEqual(self.statuses(text), [])

    def test_things_that_are_not_paths(self):
        text = "\n".join([
            "Use Node.js and/or Deno, e.g. v1.2.3 on TCP/IP.",
            "Call `os.path.join` and `json.dumps`; ratio 3/4; run /help.",
            "The site example.com is fine. Price is 4.50 and files are *.md.",
            "Set $HOME/x.txt or <name>.md later. I/O is input/output.",
            "It's 'fine' and that's 'all'.",
        ])
        self.assertEqual(self.statuses(text), [])

    def test_domain_with_a_path_is_a_destination(self):
        self.assertEqual(self.statuses("Code is at github.com/someone/project.git"),
                         [("github.com/someone/project.git", "unverified")])

    def test_dotfiles_and_folders(self):
        self.write("conf/.env.example")
        os.makedirs(os.path.join(self.root, "dist"))
        got = hc.analyze("Made `conf/.env.example` and the `dist/` folder.", self.root)
        self.assertEqual([(i["target"], i["status"]) for i in got],
                         [("conf/.env.example", "landed"), ("dist", "landed")])
        self.assertEqual(got[1]["notes"], ["folder"])

    def test_empty_file_is_flagged(self):
        self.write("empty.md", "")
        items = hc.analyze("Wrote empty.md", self.root)
        self.assertEqual(items[0]["notes"], ["empty file, 0 bytes"])

    def test_same_file_twice_is_listed_once(self):
        self.write("a.md")
        self.assertEqual(self.statuses("a.md is ready.\nAgain: ./a.md"), [("a.md", "landed")])

    def test_crlf_and_bom_report(self):
        self.write("a.md")
        self.assertEqual(self.statuses("﻿Line one\r\nWrote a.md\r\n"), [("a.md", "landed")])
        items = hc.analyze("﻿Line one\r\nWrote a.md\r\n", self.root)
        self.assertEqual(items[0]["line"], 2)

    def test_extra_delivery_words(self):
        self.write("a.md")
        self.assertEqual(self.statuses("Faxed a.md")[0][1], "landed")
        got = self.statuses("Faxed a.md", extra_delivery_words=["faxed"])
        self.assertEqual([s for _, s in got], ["prepared", "unverified"])


class NoAbsolutePaths(Case):
    def test_absolute_claims_are_printed_relative_or_masked(self):
        inside = self.write("out/in side.md")
        outside_dir = os.path.realpath(tempfile.mkdtemp(prefix="hoc outside "))
        self.addCleanup(shutil.rmtree, outside_dir, True)
        outside = os.path.join(outside_dir, "far.md")
        with open(outside, "w") as handle:
            handle.write("x")
        gone = os.path.join(outside_dir, "gone.md")
        report = "Wrote `%s`, `%s` and `%s`.\n" % (inside, outside, gone)
        code, out, err = self.run_script(report)
        self.assertEqual(code, 1)
        self.assertIsNone(ABSOLUTE_RE.search(out), out)
        self.assertNotIn(self.root, out)
        self.assertNotIn(outside_dir, out)
        self.assertIn("out/in side.md", out)
        self.assertIn("<outside root>/far.md", out)
        self.assertIn("<outside root>/gone.md", out)

    def test_show_absolute_opts_in(self):
        inside = self.write("a.md")
        code, out, err = self.run_script("Wrote a.md\n", ["--show-absolute"])
        self.assertIn(inside, out)

    def test_report_given_by_absolute_path_shows_only_its_name(self):
        path = self.write("sub/the report.md", "nothing here\n")
        proc = subprocess.run([sys.executable, SCRIPT, path, "--root", self.root],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out = proc.stdout.decode(locale.getpreferredencoding(False), "replace")
        self.assertIn("Report: the report.md", out)
        self.assertIsNone(ABSOLUTE_RE.search(out), out)

    def test_home_paths_are_masked(self):
        self.assertEqual(self.statuses("Wrote ~/surely-not-here-12345.md"),
                         [("<outside root>/surely-not-here-12345.md", "missing")])


class Cli(Case):
    def test_stdin(self):
        self.write("a.md")
        code, out, err = self.run_script("Wrote a.md\n", stdin=True)
        self.assertEqual(code, 0)
        self.assertIn("Report: <stdin>", out)
        code, out, err = self.run_script("Wrote a.md\n", ["-"], stdin=True)
        self.assertEqual(code, 0)

    def test_root_option(self):
        self.write("proj/a.md")
        code, out, err = self.run_script("Wrote a.md\n", ["--root", "proj"])
        self.assertEqual(code, 0)
        code, out, err = self.run_script("Wrote a.md\n", ["--root", "nope"])
        self.assertEqual(code, 2)

    def test_unreadable_report(self):
        proc = subprocess.run([sys.executable, SCRIPT, "no-such-report.md"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=self.root)
        self.assertEqual(proc.returncode, 2)
        self.assertIn(b"cannot read input", proc.stderr)
        self.assertEqual(proc.stdout, b"")

    def test_unreadable_evidence(self):
        code, out, err = self.run_script("x\n", ["--evidence", "nope.log"])
        self.assertEqual(code, 2)

    def test_utf16_report(self):
        self.write("a.md")
        path = os.path.join(self.root, "r16.md")
        with open(path, "w", encoding="utf-16") as handle:
            handle.write("Wrote a.md and b.md\n")
        proc = subprocess.run([sys.executable, SCRIPT, "r16.md"], cwd=self.root,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(proc.returncode, 1)

    def test_cp949_console_does_not_crash(self):
        self.write("café ✅.md")
        code, out, err = self.run_script("Wrote `café ✅.md` and `한글.md`\n",
                                         env={"PYTHONIOENCODING": "cp949"})
        self.assertEqual(code, 1)
        self.assertIn("한글.md", out)
        self.assertNotIn("Traceback", err)

    def test_version(self):
        proc = subprocess.run([sys.executable, SCRIPT, "--version"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertIn(hc.__version__.encode(), proc.stdout)


if __name__ == "__main__":
    unittest.main()
