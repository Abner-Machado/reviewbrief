# Security

## Reporting

Use [private vulnerability reporting](https://github.com/Abner-Machado/reviewbrief/security/advisories/new)
on this repository, rather than a public issue. No bounty, and no promised response window:
what you get is an honest answer about whether it is real and what happens next.

## What the attack surface actually is

The input is a diff, which means it is attacker-shaped whenever the diff came from a pull
request somebody else opened. Two things follow.

The parser. A hunk header with absurd numbers, a path with traversal in it, a truncated
hunk, a binary blob claiming to be text: none of that should make the tool hang, crash, or
produce a path outside the repository it was pointed at.

The signals. The brief flags things like a leftover debug print or a secret-shaped string.
A crafted diff that carries a real secret past the flag is worth reporting, because the
value of the brief is that a reviewer can trust what it surfaced. The reverse, a false
positive, is an ordinary issue.

The tool makes no network call, executes nothing it reads, and imports only the standard
library. CI checks that on every push; `scripts/make_banner.py` needs Pillow, is not
imported by the tool, and is excluded on purpose.

## What is out of scope

The brief is input for a human or a model doing the review. It does not decide anything, so
a disagreement about what it chose to surface is an issue, not a vulnerability.
