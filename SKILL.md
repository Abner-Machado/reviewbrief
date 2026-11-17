---
name: reviewbrief
description: Review a code change with line numbers that exist. Use when asked to review a diff, a pull request, a branch or staged changes. Runs a local CLI that prints every added line with its real path and line number, then reviews from that output instead of from an unanchored diff.
---

# reviewbrief

## When this applies

Any request to review changed code: a diff, staged changes, a branch against main, a
patch file, a pull request. Not for reviewing a whole file that nobody changed, and not
for writing new code.

## Why run the tool first

A diff tells you what changed. It does not tell you the line number in the new file,
because the number advances on added and context lines but not on removed ones. Citing
a line you worked out in your head is how a review ends up pointing at nothing. Run the
tool and cite from its output.

## How to run it

```bash
git diff | python reviewbrief.py              # unstaged
git diff --staged | python reviewbrief.py     # staged
git diff main...HEAD | python reviewbrief.py  # branch
python reviewbrief.py --diff some.patch       # a saved patch
```

Add `--json` when you want the structure instead of the text.

Exit `1` means the input was empty or was not a git diff. Exit `2` means a file could
not be read. Neither is a reason to guess: report what happened and stop.

## How to review from it

Everything you cite carries a `path:line` taken from the brief. A line number you cannot
find in the brief is a line number you may not use.

Cover correctness, security, performance, clarity, and tests. Skip any of them when the
diff gives you nothing real to say.

Separate what you verified from what you suspect. Give the failing scenario: an input, a
state, and the wrong output. No praise, no summary paragraph, no restating the diff.
Rank by consequence, worst first.

When the diff does not show enough to judge something, say so and name the file you
would need to read.

## The signals

The brief marks added lines matching six regular expressions: `secret-like`,
`debug-leftover`, `todo-added`, `broad-catch`, `sleep-in-code`, plus a note when no test
file changed.

These are not findings. Confirm each one against the line and drop it when the line is
fine. A `print(` in a command line tool is the program working. Equally, a line with no
signal can still be the worst line in the change, so read the whole brief.
