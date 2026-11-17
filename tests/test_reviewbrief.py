"""Tests for reviewbrief. Standard library only: python tests/test_reviewbrief.py"""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import reviewbrief as rb  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLI = os.path.join(ROOT, "reviewbrief.py")

SAMPLE = """\
diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -10,6 +10,9 @@ def handler(req):
     name = req.get("name")
-    return render(name)
+    print("debug", name)
+    query = "SELECT * FROM users WHERE name = '" + name + "'"
+    api_key = "sk-abcdef0123456789"
+    return db.run(query)
diff --git a/README.md b/README.md
index 3333333..4444444 100644
--- a/README.md
+++ b/README.md
@@ -1,2 +1,3 @@
 # Title
+One added line.
"""


class TestParsing(unittest.TestCase):
    def setUp(self):
        self.files = rb.parse_diff(SAMPLE)

    def test_finds_both_files(self):
        self.assertEqual([f.path for f in self.files], ["src/app.py", "README.md"])

    def test_line_numbers_are_real(self):
        """The first added line of a hunk starting at 10 must be numbered 10."""
        app = self.files[0]
        numbers = [l.number for h in app.hunks for l in h.added]
        self.assertEqual(numbers, [11, 12, 13, 14])

    def test_context_advances_the_counter(self):
        app = self.files[0]
        first = app.hunks[0].added[0]
        self.assertIn("print(", first.text)
        self.assertEqual(first.number, 11)

    def test_counts(self):
        app = self.files[0]
        self.assertEqual(app.added_count, 4)
        self.assertEqual(app.removed_count, 1)

    def test_language_detection(self):
        self.assertEqual(self.files[0].language, "python")
        self.assertEqual(self.files[1].language, "markdown")

    def test_signals_are_found(self):
        app = self.files[0]
        found = {s for h in app.hunks for l in h.added for s in l.signals}
        self.assertIn("debug-leftover", found)
        self.assertIn("secret-like", found)

    def test_markdown_only_line_has_no_signal(self):
        readme = self.files[1]
        self.assertEqual([l.signals for h in readme.hunks for l in h.added], [[]])


class TestClassification(unittest.TestCase):
    def test_test_paths(self):
        for p in ["tests/test_x.py", "src/__tests__/a.js", "a/b_test.go",
                  "x.test.ts", "spec/models/user_spec.rb", "app/test/T.java"]:
            self.assertTrue(rb.looks_like_test(p), p)

    def test_non_test_paths(self):
        for p in ["src/latest.py", "contest.go", "src/protest/a.js", "testament.rb"]:
            self.assertFalse(rb.looks_like_test(p), p)

    def test_untested_flags_source_without_tests(self):
        self.assertEqual(rb.untested(rb.parse_diff(SAMPLE)), ["src/app.py"])

    def test_untested_is_silent_when_a_test_changed(self):
        diff = SAMPLE + """\
diff --git a/tests/test_app.py b/tests/test_app.py
--- a/tests/test_app.py
+++ b/tests/test_app.py
@@ -1,1 +1,2 @@
 import app
+def test_new(): pass
"""
        self.assertEqual(rb.untested(rb.parse_diff(diff)), [])


class TestEdgeCases(unittest.TestCase):
    def test_new_file_marked(self):
        diff = ("diff --git a/n.py b/n.py\nnew file mode 100644\n--- /dev/null\n"
                "+++ b/n.py\n@@ -0,0 +1,1 @@\n+x = 1\n")
        f = rb.parse_diff(diff)[0]
        self.assertTrue(f.is_new)
        self.assertEqual(f.hunks[0].added[0].number, 1)

    def test_deleted_file_marked(self):
        diff = ("diff --git a/d.py b/d.py\ndeleted file mode 100644\n--- a/d.py\n"
                "+++ /dev/null\n@@ -1,1 +0,0 @@\n-x = 1\n")
        f = rb.parse_diff(diff)[0]
        self.assertTrue(f.is_deleted)
        self.assertEqual(f.added_count, 0)

    def test_binary_file_marked_and_rendered_without_lines(self):
        diff = ("diff --git a/i.png b/i.png\nindex 1..2 100644\n"
                "Binary files a/i.png and b/i.png differ\n")
        files = rb.parse_diff(diff)
        self.assertTrue(files[0].is_binary)
        self.assertIn("No textual lines to review", rb.render_markdown(files))

    def test_rename_updates_path(self):
        diff = ("diff --git a/old.py b/new.py\nsimilarity index 95%\n"
                "rename from old.py\nrename to new.py\n")
        self.assertEqual(rb.parse_diff(diff)[0].path, "new.py")

    def test_no_newline_marker_does_not_shift_numbers(self):
        diff = ("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"
                "@@ -1,1 +1,2 @@\n a = 1\n+b = 2\n\\ No newline at end of file\n")
        f = rb.parse_diff(diff)[0]
        self.assertEqual([l.number for h in f.hunks for l in h.added], [2])

    def test_several_hunks_keep_separate_numbering(self):
        diff = ("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"
                "@@ -1,1 +1,2 @@\n x\n+first\n"
                "@@ -40,1 +41,2 @@\n y\n+second\n")
        f = rb.parse_diff(diff)[0]
        self.assertEqual([l.number for h in f.hunks for l in h.added], [2, 42])

    def test_empty_diff_parses_to_nothing(self):
        self.assertEqual(rb.parse_diff(""), [])

    def test_plus_plus_plus_is_not_an_added_line(self):
        f = rb.parse_diff(SAMPLE)[0]
        texts = [l.text for h in f.hunks for l in h.added]
        self.assertFalse(any(t.startswith("+ b/") for t in texts))


class TestOutput(unittest.TestCase):
    def test_markdown_carries_the_line_numbers(self):
        md = rb.render_markdown(rb.parse_diff(SAMPLE))
        self.assertIn("src/app.py", md)
        self.assertIn("    11  ", md)

    def test_no_policy_omits_the_instructions(self):
        md = rb.render_markdown(rb.parse_diff(SAMPLE), policy=False)
        self.assertNotIn("Code review request", md)
        self.assertIn("## Brief", md)

    def test_json_round_trips(self):
        payload = json.loads(json.dumps(rb.to_jsonable(rb.parse_diff(SAMPLE))))
        self.assertEqual(payload["summary"]["files"], 2)
        self.assertEqual(payload["files"][0]["path"], "src/app.py")
        self.assertEqual(payload["files"][0]["hunks"][0]["added"][0]["number"], 11)


class TestCliFailurePaths(unittest.TestCase):
    """A green happy path proves nothing. These are the paths that matter."""

    def run_cli(self, args, stdin=""):
        return subprocess.run([sys.executable, "-I", CLI] + args,
                              input=stdin, capture_output=True, text=True)

    def test_empty_stdin_exits_1(self):
        r = self.run_cli([], stdin="")
        self.assertEqual(r.returncode, 1)
        self.assertIn("empty", r.stderr)

    def test_garbage_input_exits_1_and_says_why(self):
        r = self.run_cli([], stdin="this is not a diff at all\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("diff --git", r.stderr)

    def test_missing_file_exits_2(self):
        r = self.run_cli(["--diff", os.path.join(HERE, "does-not-exist.patch")])
        self.assertEqual(r.returncode, 2)
        self.assertIn("cannot read", r.stderr)

    def test_valid_diff_exits_0(self):
        r = self.run_cli([], stdin=SAMPLE)
        self.assertEqual(r.returncode, 0)
        self.assertIn("src/app.py", r.stdout)

    def test_json_flag_emits_valid_json(self):
        r = self.run_cli(["--json"], stdin=SAMPLE)
        self.assertEqual(r.returncode, 0)
        json.loads(r.stdout)

    def test_diff_from_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".patch", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(SAMPLE)
            path = fh.name
        try:
            r = self.run_cli(["--diff", path])
            self.assertEqual(r.returncode, 0)
            self.assertIn("Brief", r.stdout)
        finally:
            os.unlink(path)



BS = chr(92)


class TestCombinedDiff(unittest.TestCase):
    """A merge diff carries one column per parent. Guessing would produce
    confident, wrong line numbers, so the parser refuses instead."""

    MERGE = "diff --cc src/a.py\n@@@ -1,2 -1,2 +1,3 @@@\n  ctx\n++x = 1\n"

    def test_parse_raises(self):
        with self.assertRaises(rb.CombinedDiff):
            rb.parse_diff(self.MERGE)

    def test_cli_exits_1_and_names_the_cause(self):
        r = subprocess.run([sys.executable, "-I", CLI], input=self.MERGE,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("combined (merge) diff", r.stderr)
        self.assertIn("HEAD^1", r.stderr)

    def test_plain_diff_still_parses(self):
        self.assertEqual(len(rb.parse_diff(SAMPLE)), 2)


class TestHeaderPaths(unittest.TestCase):
    @staticmethod
    def header(h):
        return rb.parse_diff(h + "\n--- a/x\n+++ b/x\n@@ -1,1 +1,2 @@\n x\n+y\n")[0]

    def test_plain_path(self):
        self.assertEqual(self.header("diff --git a/src/app.py b/src/app.py").path,
                         "src/app.py")

    def test_path_with_a_space(self):
        f = self.header("diff --git a/my file.py b/my file.py")
        self.assertEqual(f.path, "my file.py")
        self.assertEqual(f.language, "python")

    def test_quoted_path_with_an_accent(self):
        """Git quotes a non-ASCII path and keeps the prefix inside the quotes."""
        esc = BS + "303" + BS + "251"
        f = self.header('diff --git "a/caf%s.py" "b/caf%s.py"' % (esc, esc))
        self.assertEqual(f.path, "caf" + chr(233) + ".py")
        self.assertEqual(f.language, "python")

    def test_rename_target_wins(self):
        self.assertEqual(self.header("diff --git a/old/name.py b/new/name.py").path,
                         "new/name.py")

    def test_directory_named_b_does_not_confuse_it(self):
        self.assertEqual(self.header("diff --git a/src/b/x.py b/src/b/x.py").path,
                         "src/b/x.py")

    def test_unquote_strips_the_prefix_only_once(self):
        self.assertEqual(rb.unquote_path("b/b/thing.py"), "b/thing.py")


class TestUntestedPairing(unittest.TestCase):
    @staticmethod
    def build(paths):
        out = ""
        for p in paths:
            out += ("diff --git a/%s b/%s\n--- a/x\n+++ b/x\n"
                    "@@ -1,1 +1,2 @@\n x\n+y\n" % (p, p))
        return rb.parse_diff(out)

    def test_unrelated_test_does_not_silence_the_diff(self):
        """The old all-or-nothing rule let one stray test hide every source file."""
        files = self.build(["src/m0.py", "src/m1.py", "tests/test_other.py"])
        self.assertEqual(rb.untested(files), ["src/m0.py", "src/m1.py"])

    def test_related_test_silences_only_its_pair(self):
        files = self.build(["src/app.py", "src/other.py", "tests/test_app.py"])
        self.assertEqual(rb.untested(files), ["src/other.py"])

    def test_other_naming_conventions_pair_too(self):
        for src, test in [("src/app.ts", "src/app.test.ts"),
                          ("lib/user.rb", "spec/user_spec.rb"),
                          ("main/Cart.java", "test/CartTest.java")]:
            self.assertEqual(rb.untested(self.build([src, test])), [], (src, test))

    def test_non_source_files_are_never_flagged(self):
        self.assertEqual(rb.untested(self.build(["README.md", "a.yml"])), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
