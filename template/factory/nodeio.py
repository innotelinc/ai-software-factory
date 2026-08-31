"""A node's stdout is its VALUE. Everything else goes to stderr, automatically.

    from nodeio import note, emit          # importing this is the whole mechanism

    note("PREFLIGHT_OK secrets_ignored=4") # -> stderr
    print("anything at all")               # -> stderr TOO. That is the point.
    emit({"target": target, "branch": branch})  # -> the real stdout, once

THE BUG THIS EXISTS TO PREVENT, found twice by running it, the second time AFTER a
fix that only addressed the first.

A script node that declares an `output_format` has its stdout parsed as JSON, so a
single friendly line before the payload makes the whole thing unparseable -- and the
error surfaces on the CONSUMER, several nodes downstream:

    'gate-plan' failed: '$preflight.output.target' references field 'target', but
    node 'preflight's output is not a JSON object

Which reads as "gate-plan is broken" and sends you to the wrong file entirely.

The first fix rewrote every `print()` in the script itself. It did not work, and the
reason is the interesting part: **the polluting line was not in the script.** It came
from `guard.preflight()` -- a library function in `factory/`, doing exactly what it
should, printing a marker that is load-bearing when the guard runs as a CLI because
the gate greps that stdout. Two callers, two correct-but-incompatible meanings for
one stream.

So this does not ask anyone to remember. **Importing this module redirects
`sys.stdout` to `sys.stderr` for the whole process**, and `emit()` writes to the real
stdout captured at import time. Every library a node imports is then automatically
safe, including ones written later by someone who never read this file.

    stdout  the machine's channel. Exactly one JSON object, or nothing.
    stderr  the human's channel. Archon streams it live and retains it in the run,
            so nothing is lost by going there -- it is simply not mistaken for a value.

Import it FIRST, before anything that might print at import time.
"""

from __future__ import annotations

import json
import sys

# The real stdout, captured before it is taken away. This is the only handle that
# reaches Archon's value channel.
_VALUE = sys.stdout

# UTF-8 ON EVERY STREAM, UNCONDITIONALLY, and this is not housekeeping.
#
# Windows defaults stdio to the ANSI codepage. A node that writes one non-ASCII
# character -- an arrow in a comment, a curly quote in an issue title, an accent in
# somebody's name -- dies with `UnicodeEncodeError: 'charmap' codec can't encode`,
# and it dies at the WRITE, after all the work is done.
#
# It happened here on the character `<=`, inside a document being handed to the
# judge. Milder versions are worse: the same defaulting has put a perfectly correct
# rejection comment on GitHub with every non-ASCII character replaced by a
# replacement glyph, exiting 0 the whole way, with nothing checked afterwards except
# the exit code.
#
# Doing it here means every node gets it by importing one module, rather than by
# each author remembering.
for _s in (_VALUE, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

# THE REDIRECT. Everything that prints from here on -- this script, every factory
# module it imports, every library any of those import -- lands on stderr where a
# person can read it and no parser will mistake it for a value.
sys.stdout = sys.stderr

_EMITTED = False


def note(*parts: object) -> None:
    """Say something to the person watching. Never reaches the value channel."""
    print(*parts, file=sys.stderr, flush=True)


def emit(payload: dict) -> None:
    """The node's value, as a field-readable object. Call it once, last.

    Calling it twice is a bug and says so rather than writing two JSON objects to one
    stream, which parses as neither.
    """
    _write(json.dumps(payload))


def emit_text(document: str) -> None:
    """The node's value, as a document.

    For a node whose output is prose rather than fields -- a brief substituted into
    the next node's prompt, a rendered report. Same one-call rule, same stream.
    """
    _write(document)


def _write(value: str) -> None:
    global _EMITTED
    if _EMITTED:
        note(
            "NODEIO_WARNING: the value was emitted more than once. A node has ONE "
            "value; a second write would make stdout unparseable for every consumer. "
            "Ignored."
        )
        return
    _EMITTED = True
    _VALUE.write(value)
    _VALUE.flush()


def die(message: str, code: int = 1) -> "None":
    """Fail loudly, on stderr, with nothing on the value channel.

    A failing node must not emit a partial value: a consumer reading `.field` off a
    half-written object gets a confident wrong answer instead of a loud stop.
    """
    note(message)
    raise SystemExit(code)
