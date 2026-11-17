#!/usr/bin/env python3
"""reviewbrief - build the brief a code reviewer actually needs.

Reads a unified diff and emits a review brief in which every changed line
carries its real path and line number, so a reviewer (human or model) can cite
a location that exists instead of guessing one.

Standard library only. No network. No install.

    git diff | python reviewbrief.py
    git diff main...HEAD | python reviewbrief.py --format markdown
    python reviewbrief.py --diff saved.patch --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict

__version__ = "0.1.0"

BACKSLASH = chr(92)

# ---------------------------------------------------------------- languages

EXT_LANG = {
    ".py": "python", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".jsx": "javascript",
    ".rs": "rust", ".go": "go", ".java": "java", ".rb": "ruby", ".php": "php",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".cs": "csharp",
    ".sh": "shell", ".bash": "shell", ".ps1": "powershell", ".sql": "sql",
    ".html": "html", ".css": "css", ".yml": "yaml", ".yaml": "yaml",
    ".json": "json", ".toml": "toml", ".md": "markdown",
}

SOURCE_LANGS = {
    "python", "javascript", "typescript", "rust", "go", "java",
    "ruby", "php", "c", "cpp", "csharp",
}


def language_of(path: str) -> str:
    lowered = path.lower()
    for ext, lang in EXT_LANG.items():
        if lowered.endswith(ext):
            return lang
    return "unknown"


JVM_TEST_RE = re.compile(
    r"(?:^|/)(?:Test[A-Z0-9]\w*|\w+(?:Test|Tests|Spec|IT))\.(?:java|kt|kts|scala|cs)$")

TEST_DIRS = {"test", "tests", "spec", "specs", "__tests__", "testing"}


def looks_like_test(path: str) -> bool:
    """Does this path look like a test file, by the conventions people use?

    The leading slash matters: without it a top-level `test/` directory fails a
    naive `"/test/" in path` check, which is how `test/CartTest.java` once got
    through as production code.
    """
    p = "/" + path.replace(BACKSLASH, "/").lstrip("/")
    lowered = p.lower()
    name = lowered.rsplit("/", 1)[-1]

    if any("/" + d + "/" in lowered for d in TEST_DIRS):
        return True
    if JVM_TEST_RE.search(p):
        return True
    return (
        name.startswith("test_") or name.startswith("test.")
        or "_test." in name or ".test." in name or ".spec." in name
        or "_spec." in name or name.endswith("_test.go")
    )


# ---------------------------------------------------------------- signals
# Each signal is deterministic and reports only what is literally present.
# None of them is a verdict. They mark lines worth a human sentence.

SIGNALS = [
    ("secret-like", re.compile(
        r"""(?ix)
        \b(?:AKIA[0-9A-Z]{16})\b
        | -----BEGIN \s (?:RSA|OPENSSH|DSA|EC|PGP) \s PRIVATE \s KEY-----
        | \b(?:api[_-]?key|secret|passwd|password|token|access[_-]?key)\b
          \s* [:=] \s* ['"][^'"\s]{8,}['"]
        """)),
    ("debug-leftover", re.compile(
        r"""(?x)
        \bconsole\.(?:log|debug|dir)\s*\(
        | \bdebugger\b
        | \bprint\s*\(
        | \bdbg!\s*\(
        | \bfmt\.Print(?:ln|f)?\s*\(
        | \bSystem\.out\.print(?:ln)?\s*\(
        | \bvar_dump\s*\(
        """)),
    ("todo-added", re.compile(r"(?i)\b(?:TODO|FIXME|XXX|HACK)\b")),
    ("broad-catch", re.compile(
        r"""(?x)
        ^\s*except\s*:
        | ^\s*except\s+(?:BaseException|Exception)\s*(?:as\s+\w+\s*)?:
        | \bcatch\s*\([^)]*\)\s*\{\s*\}
        | \.unwrap\(\)
        """)),
    ("sleep-in-code", re.compile(
        r"""(?x)
        \btime\.sleep\s*\(
        | \bsetTimeout\s*\(
        | \bThread\.sleep\s*\(
        | \bStart-Sleep\b
        """)),
]


@dataclass
class Line:
    number: int
    text: str
    signals: list = field(default_factory=list)


@dataclass
class Hunk:
    header: str
    start: int
    added: list = field(default_factory=list)      # list[Line]
    removed_count: int = 0


@dataclass
class FileChange:
    path: str
    language: str = "unknown"
    is_test: bool = False
    is_new: bool = False
    is_deleted: bool = False
    is_binary: bool = False
    hunks: list = field(default_factory=list)      # list[Hunk]

    @property
    def added_count(self) -> int:
        return sum(len(h.added) for h in self.hunks)

    @property
    def removed_count(self) -> int:
        return sum(h.removed_count for h in self.hunks)


HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@(.*)$")
COMBINED_RE = re.compile(r"^diff --(?:cc|combined) ")


class CombinedDiff(Exception):
    """A merge diff. Its hunk headers carry one column per parent, so the
    single-parent line arithmetic here does not apply and would lie."""


def unquote_path(token: str) -> str:
    """Strip git's quoting and the a/ or b/ prefix from one path token.

    Git quotes a path that holds a space, a quote or a non-ASCII byte, and the
    quoted form keeps the prefix inside the quotes: "b/cafÃ©.py".
    """
    token = token.strip()
    if len(token) >= 2 and token[0] == '"' and token[-1] == '"':
        inner = token[1:-1]
        try:
            token = inner.encode("latin-1", "backslashreplace").decode("unicode_escape")
            token = token.encode("latin-1", "replace").decode("utf-8", "replace")
        except (UnicodeDecodeError, UnicodeEncodeError):
            token = inner
    if token.startswith("a/") or token.startswith("b/"):
        token = token[2:]
    return token


def split_header_tokens(rest: str) -> list:
    """Split the two path tokens of a diff header, honoring git quoting.

    Written as a scanner instead of a regular expression: the pattern needs
    escaped backslashes inside an escaped string, and that is exactly the kind
    of line that breaks silently when somebody edits it later.
    """
    tokens: list = []
    i = 0
    n = len(rest)
    while i < n:
        while i < n and rest[i] == " ":
            i += 1
        if i >= n:
            break
        if rest[i] == '"':
            j = i + 1
            while j < n:
                if rest[j] == BACKSLASH:
                    j += 2
                    continue
                if rest[j] == '"':
                    break
                j += 1
            tokens.append(rest[i:min(j + 1, n)])
            i = j + 1
        else:
            j = rest.find(" ", i)
            if j == -1:
                tokens.append(rest[i:])
                break
            tokens.append(rest[i:j])
            i = j
    return tokens


def path_from_header(raw: str) -> str:
    """Pull the destination path out of a 'diff --git a/x b/x' header.

    The unquoted form is ambiguous because a path may contain spaces, so the
    halves are compared first: git writes the same path twice unless the file
    was renamed.
    """
    rest = raw[len("diff --git "):].strip()

    if rest.startswith('"'):
        tokens = split_header_tokens(rest)
        if len(tokens) >= 2:
            return unquote_path(tokens[-1])
        if tokens:
            return unquote_path(tokens[0])

    half = len(rest) // 2
    if rest[:half].strip() == rest[half:].strip():
        return unquote_path(rest[half:])

    idx = rest.find(" b/")
    if idx != -1:
        return unquote_path(rest[idx + 1:])
    return unquote_path(rest.split()[-1])


def parse_diff(text: str) -> list:
    """Parse a unified diff. Returns FileChange objects with real line numbers.

    Raises CombinedDiff when handed a merge diff, because the arithmetic here
    assumes one parent and would produce confident, wrong line numbers.
    """
    files: list = []
    current: FileChange | None = None
    hunk: Hunk | None = None
    new_lineno = 0

    for raw in text.splitlines():
        if COMBINED_RE.match(raw):
            raise CombinedDiff(raw.split()[-1])

        if raw.startswith("diff --git "):
            current = None
            hunk = None
            path = path_from_header(raw)
            current = FileChange(path=path, language=language_of(path),
                                 is_test=looks_like_test(path))
            files.append(current)
            continue

        if current is None:
            continue

        if raw.startswith("new file mode"):
            current.is_new = True
            continue
        if raw.startswith("deleted file mode"):
            current.is_deleted = True
            continue
        if raw.startswith("Binary files ") or raw.startswith("GIT binary patch"):
            current.is_binary = True
            continue
        if raw.startswith("rename to "):
            current.path = unquote_path(raw[len("rename to "):])
            current.language = language_of(current.path)
            current.is_test = looks_like_test(current.path)
            continue

        m = HUNK_RE.match(raw)
        if m:
            new_lineno = int(m.group(1))
            hunk = Hunk(header=raw, start=new_lineno)
            current.hunks.append(hunk)
            continue

        if hunk is None:
            continue

        if raw.startswith("+") and not raw.startswith("+++"):
            body = raw[1:]
            found = [name for name, rx in SIGNALS if rx.search(body)]
            hunk.added.append(Line(number=new_lineno, text=body, signals=found))
            new_lineno += 1
        elif raw.startswith("-") and not raw.startswith("---"):
            hunk.removed_count += 1
        elif raw.startswith(" "):
            new_lineno += 1
        elif raw == "\\ No newline at end of file":
            continue

    return files


def untested(files: list) -> list:
    """Source files that changed with no plausibly related test file in the diff.

    A changed test counts for a source file when the source file's stem appears
    somewhere in the test's path, which is what every common convention does:
    test_app.py, app.test.ts, AppTest.java, app_spec.rb. One unrelated test file
    no longer silences the whole diff.
    """
    test_paths = [f.path.lower().replace("\\", "/") for f in files if f.is_test]
    out = []
    for f in files:
        if f.is_test or f.is_binary or f.is_deleted or f.language not in SOURCE_LANGS:
            continue
        name = f.path.replace("\\", "/").rsplit("/", 1)[-1]
        stem = name.rsplit(".", 1)[0].lower()
        if stem and any(stem in p for p in test_paths):
            continue
        out.append(f.path)
    return out


def summarize(files: list) -> dict:
    counts: dict = {}
    for f in files:
        for h in f.hunks:
            for ln in h.added:
                for s in ln.signals:
                    counts[s] = counts.get(s, 0) + 1
    return {
        "files": len(files),
        "added": sum(f.added_count for f in files),
        "removed": sum(f.removed_count for f in files),
        "languages": sorted({f.language for f in files if f.language != "unknown"}),
        "signals": counts,
        "source_files_without_test_changes": untested(files),
    }


# ---------------------------------------------------------------- rendering

POLICY = """\
Review the diff below. Everything you cite must exist in it: every claim carries a
`path:line` taken from the brief, and a line number you cannot find in the brief is a
line number you may not use.

Cover these, and skip a heading when the diff gives you nothing real to say about it:

1. Correctness. Logic errors, unhandled edge cases, null and undefined paths, off-by-one,
   wrong operator, a condition that cannot be reached.
2. Security. Injection through string-built queries or commands, unvalidated input
   crossing a trust boundary, authentication and authorization gaps, a secret in source.
3. Performance. Work inside a loop that belongs outside it, an unbounded read, a resource
   opened and never closed, an obvious N+1.
4. Clarity and structure. Naming that misleads, a function doing several jobs, duplication
   this diff introduced. Say it once, and do not rewrite working code to taste.
5. Tests. Which added branch has no test, and the smallest case that would catch the bug
   you just described.

Rules that decide whether the review is worth reading:

- Separate what you verified in the diff from what you suspect. Write "this is" only for
  the first, and "this may be, because" for the second.
- Give the failing scenario. An input, a state, and the wrong output beats an adjective.
- No praise, no summary paragraph, no restating the diff back.
- Say explicitly when the diff does not show enough to judge something, and name the file
  you would need to read.
- Rank what you found by consequence, worst first.

The signals in the brief are matches of a plain regular expression, not findings. Confirm
each one against the line before you report it, and drop it if the line is fine.
"""


def render_markdown(files: list, policy: bool = True) -> str:
    out: list = []
    s = summarize(files)

    if policy:
        out.append("# Code review request\n")
        out.append(POLICY)
        out.append("")

    out.append("## Brief\n")
    out.append(f"- Files changed: {s['files']}")
    out.append(f"- Lines added: {s['added']}, removed: {s['removed']}")
    if s["languages"]:
        out.append(f"- Languages: {', '.join(s['languages'])}")
    if s["signals"]:
        pairs = ", ".join(f"{k} x{v}" for k, v in sorted(s["signals"].items()))
        out.append(f"- Signals to confirm: {pairs}")
    if s["source_files_without_test_changes"]:
        out.append("- Changed with no matching test file in this diff: "
                   + ", ".join(s["source_files_without_test_changes"]))
    out.append("")

    for f in files:
        tags = []
        if f.is_new:
            tags.append("new file")
        if f.is_deleted:
            tags.append("deleted")
        if f.is_binary:
            tags.append("binary")
        if f.is_test:
            tags.append("test")
        label = f" ({', '.join(tags)})" if tags else ""
        out.append(f"### {f.path}{label}")
        out.append(f"Language: {f.language}. +{f.added_count} / -{f.removed_count}\n")

        if f.is_binary or not f.hunks:
            out.append("_No textual lines to review._\n")
            continue

        for h in f.hunks:
            out.append(f"`{h.header.strip()}`\n")
            out.append("```")
            for ln in h.added:
                mark = ("   <- " + ", ".join(ln.signals)) if ln.signals else ""
                out.append(f"{ln.number:>6}  {ln.text}{mark}")
            out.append("```\n")

    return "\n".join(out)


def to_jsonable(files: list) -> dict:
    return {
        "version": __version__,
        "summary": summarize(files),
        "files": [
            {
                **{k: v for k, v in asdict(f).items() if k != "hunks"},
                "added_count": f.added_count,
                "removed_count": f.removed_count,
                "hunks": [
                    {
                        "header": h.header,
                        "start": h.start,
                        "removed_count": h.removed_count,
                        "added": [asdict(l) for l in h.added],
                    }
                    for h in f.hunks
                ],
            }
            for f in files
        ],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="reviewbrief",
        description="Build the brief a code reviewer needs, with real line numbers.")
    ap.add_argument("--diff", metavar="FILE",
                    help="read the diff from FILE instead of standard input")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of markdown")
    ap.add_argument("--no-policy", action="store_true",
                    help="emit the brief alone, without the review instructions")
    ap.add_argument("--version", action="version", version=f"reviewbrief {__version__}")
    args = ap.parse_args(argv)

    if args.diff:
        try:
            with open(args.diff, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError as exc:
            print(f"reviewbrief: cannot read {args.diff}: {exc}", file=sys.stderr)
            return 2
    else:
        if sys.stdin.isatty():
            print("reviewbrief: no diff on standard input. "
                  "Try: git diff | reviewbrief.py", file=sys.stderr)
            return 2
        text = sys.stdin.read()

    if not text.strip():
        print("reviewbrief: the diff is empty, nothing to review.", file=sys.stderr)
        return 1

    try:
        files = parse_diff(text)
    except CombinedDiff as exc:
        print("reviewbrief: this is a combined (merge) diff, seen at "
              f"'{exc}'. Its hunk headers carry one column per parent, so the "
              "line numbers here would be wrong. Review the merge against one "
              "parent instead, for example: git diff HEAD^1 HEAD",
              file=sys.stderr)
        return 1
    if not files:
        print("reviewbrief: no 'diff --git' header found. "
              "This does not look like a git unified diff.", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(to_jsonable(files), indent=2))
    else:
        print(render_markdown(files, policy=not args.no_policy))
    return 0


if __name__ == "__main__":
    sys.exit(main())
