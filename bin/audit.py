#!/usr/bin/env python3
"""Audit the MACHINERY, not your repo.

    python bin/audit.py                 # the shipped template
    python bin/audit.py --repo ../tally # a factory somebody installed

`darkfactory doctor` asks "is this repository set up correctly?" -- protected files,
a real holdout, a calibrated ratchet, a channel that can reach you. This asks a
different question: **is the machinery underneath it still sound?**

A correctly configured repo running broken machinery passes every check the doctor
has. The findings here are bugs in the factory rather than gaps in your setup.

WHY IT EXISTS. Every check below is a failure shape that actually happened, and every
one of them was invisible to both the doctor and to Archon's own workflow validation
-- because each is a property that spans two files. A node emits a value; a different
node reads it. A state exists in one table; its label lives in another. A marker is
required by config; the thing that prints it is a harness the config has never seen.

Nothing here needs an API key, a model, or a running app. It reads files.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

HOME = Path(__file__).resolve().parent.parent

FINDINGS: list[tuple[str, str, str]] = []  # (severity, check, detail)


def fail(check: str, detail: str) -> None:
    FINDINGS.append(("FAIL", check, detail))


def warn(check: str, detail: str) -> None:
    FINDINGS.append(("warn", check, detail))


def load_yaml(path: Path) -> dict:
    try:
        import yaml  # type: ignore
    except ImportError:
        return _mini_yaml(path)
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _mini_yaml(path: Path) -> dict:
    """Enough of a parser to find node ids and output_format keys without a dependency.

    Deliberately crude: this audit must run anywhere, including a fresh checkout with
    nothing installed. If PyYAML is present it is used instead.
    """
    text = path.read_text(encoding="utf-8")
    nodes = []
    for m in re.finditer(r"^  - id:\s*(\S+)", text, re.M):
        nodes.append({"id": m.group(1)})
    return {"_raw": text, "nodes": nodes}


# ---------------------------------------------------------------------------


def check_node_outputs(root: Path) -> None:
    """Every `$node.output.field` must be a field the producer actually declares.

    THE INCIDENT. A script printed one friendly line before its JSON payload, so the
    payload was unparseable -- and the error surfaced on the CONSUMER two nodes later:
    "node 'preflight's output is not a JSON object". The first place anyone looks is
    the file that is not broken.

    Archon catches an undeclared FIELD at load time. What it cannot see is a producer
    whose script will not actually emit JSON at runtime, which is the next check.
    """
    pack = root / ".archon" / "workflows" / "darkfactory"
    if not pack.is_dir():
        fail("workflow pack", f"not found at {pack}")
        return

    for wf in sorted(pack.rglob("*.yaml")):
        text = wf.read_text(encoding="utf-8")
        declared: dict[str, set[str]] = {}
        for block in re.split(r"^  - id:\s*", text, flags=re.M)[1:]:
            node_id = block.split("\n", 1)[0].strip()
            props = set()
            m = re.search(r"output_format:.*?properties:(.*?)(?:\n      required:|\n  - id:|\Z)",
                          block, re.S)
            if m:
                props = set(re.findall(r"^\s{8}(\w+):", m.group(1), re.M))
            declared[node_id] = props

        for ref_node, ref_field in re.findall(r"\$([a-z][\w-]*)\.output\.(\w+)", text):
            if ref_node not in declared:
                fail(wf.stem, f"${ref_node}.output.{ref_field} references an unknown node")
            elif ref_field not in declared[ref_node]:
                fail(
                    wf.stem,
                    f"${ref_node}.output.{ref_field} is read, but '{ref_node}' declares "
                    f"{sorted(declared[ref_node]) or 'no output_format'} -- the consumer "
                    f"will fail, naming itself rather than the producer",
                )


def check_emitting_scripts(root: Path) -> None:
    """A script whose output is read by field must write ONLY its value to stdout.

    THE INCIDENT, and the reason this check is worth more than it looks. The polluting
    line was not in the script at all -- it came from a library function printing a
    marker that is load-bearing when the same module runs as a CLI. So checking the
    script's own `print()` calls is not enough; the script has to import `nodeio`,
    which redirects the stream for the whole process.
    """
    pack = root / ".archon" / "workflows" / "darkfactory"
    if not pack.is_dir():
        return

    consumed: set[str] = set()
    for wf in sorted(pack.rglob("*.yaml")):
        text = wf.read_text(encoding="utf-8")
        for block in re.split(r"^  - id:\s*", text, flags=re.M)[1:]:
            node_id = block.split("\n", 1)[0].strip()
            script = re.search(r"^\s{4}script:\s*(\S+)", block, re.M)
            if script and re.search(rf"\${re.escape(node_id)}\.output\.\w+", text):
                consumed.add(f"{wf.parent.name}/{script.group(1)}")

    for key in sorted(consumed):
        folder, name = key.split("/", 1)
        path = pack / folder / "scripts" / f"{name}.py"
        if not path.exists():
            fail("emitting script", f"{key} is read by field but {path} does not exist")
            continue
        src = path.read_text(encoding="utf-8")
        if "from nodeio import" not in src:
            fail(
                "emitting script",
                f"{key} is read by field but does not import nodeio -- any library it "
                f"imports can print to stdout and make its value unparseable",
            )
        if "emit(" not in src:
            fail("emitting script", f"{key} is read by field but never calls emit()")
        bare = [
            ln for ln in src.splitlines()
            if re.match(r"^\s*print\(", ln) and "file=sys.stderr" not in ln
        ]
        if bare:
            warn(
                "emitting script",
                f"{key} has {len(bare)} bare print() call(s). nodeio redirects them, so "
                f"this is survivable -- but note() says what you meant",
            )
        try:
            ast.parse(src)
        except SyntaxError as e:
            fail("emitting script", f"{key} does not parse: line {e.lineno}, {e.msg}")


def check_all_scripts_parse(root: Path) -> None:
    """Everything under factory/ and every workflow script compiles.

    Cheap, and it catches the class of damage a bulk edit does: a stray paren in a
    file that only runs on the escalation path, discovered at 3am on the one run that
    needed it.
    """
    for base in (root / "factory", root / ".archon" / "workflows" / "darkfactory"):
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            try:
                ast.parse(p.read_text(encoding="utf-8"))
            except SyntaxError as e:
                fail("syntax", f"{p.relative_to(root)}: line {e.lineno}, {e.msg}")


def check_scoped_grants(root: Path) -> None:
    """A scoped Bash GRANT grants nothing. Only the DENY is scoped.

    PROVEN BY PROBE, in both directions:

        allowed_tools: ["Bash(python:*)"]   -> the node has NO shell at all
        allowed_tools: [Bash]               -> the node has a shell
        denied_tools:  ["Bash(git:*)"]      -> genuinely blocks it

    The first version of this pack scoped the GRANT, on the reasonable assumption that
    a narrow allowlist is a narrow capability. The build nodes therefore ran with no
    shell: they could not run the quick gate, asked for a command, were refused, said
    so politely in prose, and exited 0. Nothing errored. A guard that silently does
    not apply is worse than no guard, and so is a grant.
    """
    pack = root / ".archon" / "workflows" / "darkfactory"
    if not pack.is_dir():
        return
    for wf in sorted(pack.rglob("*.yaml")):
        for i, line in enumerate(wf.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if stripped.startswith("allowed_tools:") and "Bash(" in stripped:
                fail(
                    "scoped grant",
                    f"{wf.stem}:{i} scopes a Bash GRANT -- that grants nothing. Use "
                    f"bare `Bash` in allowed_tools and scope the DENY instead.",
                )


def check_yaml_booleans(root: Path) -> None:
    """`enum: [yes, no]` in YAML is `[True, False]`, not two strings.

    YAML 1.1 parses bare yes/no/on/off/y/n as booleans. An enum written that way on a
    `type: string` field loads as a schema demanding a boolean for a string, and the
    model produces whatever satisfies the contradiction -- here, `summary: "test"` and
    a finding called "test issue" after two and a half minutes of genuine work.
    Nothing errors. The verdict is just quietly worthless.
    """
    pack = root / ".archon" / "workflows" / "darkfactory"
    if not pack.is_dir():
        return
    try:
        import yaml  # type: ignore
    except ImportError:
        warn("yaml booleans", "PyYAML not installed; this check was skipped")
        return
    for wf in sorted(pack.rglob("*.yaml")):
        spec = yaml.safe_load(wf.read_text(encoding="utf-8")) or {}
        for node in spec.get("nodes", []) or []:
            props = ((node.get("output_format") or {}).get("properties") or {})
            for name, definition in props.items():
                values = (definition or {}).get("enum") or []
                bools = [v for v in values if isinstance(v, bool)]
                if bools:
                    fail(
                        "yaml booleans",
                        f"{wf.stem}/{node.get('id')}.{name} has an enum containing "
                        f"{bools} -- bare yes/no/on/off are YAML booleans. Quote them.",
                    )


def check_state_labels(root: Path) -> None:
    """Every state the machine can WRITE must have a label the installer CREATES.

    THE INCIDENT. One state's label was missing from the creation table for its entire
    life. The factory worked perfectly right up to its first green gate, at which point
    the label write failed, the gate died on an unguarded line, and there was no merge,
    no escalation and no notification -- at the one moment the factory was about to do
    the thing it exists for.

    A hand-maintained list that has to agree with a dict in another file is a list with
    an expiry date on it, so the agreement is asserted rather than remembered.
    """
    state_py = root / "factory" / "state.py"
    if not state_py.exists():
        fail("state machine", "factory/state.py is missing")
        return
    src = state_py.read_text(encoding="utf-8")

    written = set(re.findall(r'"(factory:[\w-]+)"', src))
    created = set(re.findall(r'\(\s*"(factory:[\w-]+|priority:\w+)"', src))
    missing = {lbl for lbl in written if lbl.startswith("factory:")} - created
    # The stop label is read, never written by set_state.
    missing.discard("factory:attempt-")
    if missing:
        fail(
            "state machine",
            "state.py can write these labels and init-labels does not create them: "
            + " ".join(sorted(missing))
            + " -- the factory fails the moment it first tries to set that state",
        )

    # Every state in the transition table is reachable, and every reachable state has
    # somewhere to go or is deliberately terminal.
    m = re.search(r"TRANSITIONS.*?=\s*\{(.*?)\n\}", src, re.S)
    if m:
        table = m.group(1)
        keys = set(re.findall(r'^\s{4}"([\w-]+)":', table, re.M))
        targets = set(re.findall(r'"([\w-]+)"', table)) - keys
        unreachable = keys - set(re.findall(r'\{([^}]*)\}', table).__str__().split()) if False else set()
        orphan_targets = {t for t in targets if t not in keys and "-" in t or t in keys}
        for t in sorted(set(re.findall(r'"([\w-]+)"', table))):
            if t not in keys and t not in ("needs-human",):
                # A transition target with no row of its own is terminal by omission
                # rather than by design, which is the kind of thing that reads as a
                # deadlock later.
                warn("state machine", f"'{t}' is a transition target with no row in TRANSITIONS")


def check_markers(root: Path) -> None:
    """Every required marker must be something the harness can actually print.

    A marker nothing emits blocks every merge forever, and the failure reads as "the
    gate is broken" rather than "this marker was never wired up".
    """
    cfg = root / "factory" / "config.py"
    if not cfg.exists():
        return
    src = cfg.read_text(encoding="utf-8")
    m = re.search(r'"FACTORY_REQUIRED_MARKERS",\s*\n?\s*"([^"]+)"', src)
    if not m:
        warn("markers", "could not read REQUIRED_MARKERS from config.py")
        return
    required = m.group(1).split()

    emitters = ""
    for p in (root / "harness").rglob("*.py"):
        emitters += p.read_text(encoding="utf-8", errors="replace")
    for p in (root / ".factory" / "holdout").rglob("*.py"):
        emitters += p.read_text(encoding="utf-8", errors="replace")
    emitters += (root / "factory" / "guard.py").read_text(encoding="utf-8", errors="replace")

    for marker in required:
        if marker not in emitters:
            fail(
                "markers",
                f"'{marker}' is required by config.py and nothing in harness/, the "
                f"holdout or guard.py prints it -- every merge would be blocked by a "
                f"marker that cannot appear",
            )

    for essential in ("APP_STARTED", "E2E_PASSED"):
        if essential not in required:
            fail(
                "markers",
                f"{essential} is not in REQUIRED_MARKERS. It is one of the two gates "
                f"that must be code in every factory: without it, software that crashed "
                f"on startup and software that is fine look identical to the gate",
            )


def check_no_freelance_writes(root: Path) -> None:
    """Nothing outside factory/ may change GitHub state directly.

    THE INCIDENT. A correct rejection assembled in a shell pipeline reached the filer
    as two characters. Every transition was right and the entire explanation was lost.

    So every human-facing write goes through one helper that posts in a single process
    and reads it back. A node holding `gh pr merge` is a node that can merge; a node
    holding `gh issue edit` is a node that can write a state the transition table
    forbids, and then the table is decoration.
    """
    banned = [
        (r"gh\s+pr\s+merge", "merges without the merge script's re-checks"),
        (r"gh\s+pr\s+review", "approves without the gate"),
        (r"gh\s+issue\s+close", "disposes of an issue outside the transition table"),
    ]
    pack = root / ".archon" / "workflows" / "darkfactory"
    for p in list(pack.rglob("*.py")) + list(pack.rglob("*.md")) + list(pack.rglob("*.yaml")):
        text = p.read_text(encoding="utf-8", errors="replace")
        for pattern, why in banned:
            if re.search(pattern, text):
                # A prompt SAYING a node does not have gh is fine; calling it is not.
                if p.suffix == ".md" and "do not" in text.lower():
                    continue
                fail("freelance write", f"{p.relative_to(root)} contains `{pattern}` -- {why}")


def check_holdout_isolation(root: Path) -> None:
    """The holdout must not import assertion helpers from the builder's side.

    Rule 2 of the holdout: duplicate, do not import. Importing a helper from
    `harness/` re-couples the wall to code the builder can edit, and the wall is gone
    with one refactor nobody noticed. The process driver is the one carve-out --
    starting a process is not an assertion.
    """
    holdout = root / ".factory" / "holdout" / "run.py"
    if not holdout.exists():
        return
    src = holdout.read_text(encoding="utf-8")
    imports = re.findall(r"^from (\w+) import|^import (\w+)", src, re.M)
    names = {a or b for a, b in imports}
    allowed = {"appproc", "json", "os", "sys", "re", "time", "pathlib", "Path",
               "annotations", "__future__", "random", "math", "datetime", "typing"}
    for name in sorted(names - allowed):
        if (root / "harness" / f"{name}.py").exists():
            fail(
                "holdout isolation",
                f"the holdout imports '{name}' from harness/ -- the builder can edit "
                f"that, so the wall it is supposed to be behind is one refactor from "
                f"gone. Duplicate the helper instead",
            )


def check_deny_lists(root: Path) -> None:
    """Every node that can read files must be denied the holdout directory.

    A sentence in a prompt is not enforcement. If one node's deny list is missing, that
    node can read the assertions its work will be judged against -- and it will write
    code aimed at exactly those assertions instead of at the problem.
    """
    pack = root / ".archon" / "workflows" / "darkfactory"
    for wf in sorted(pack.rglob("*.yaml")):
        text = wf.read_text(encoding="utf-8")
        for block in re.split(r"^  - id:\s*", text, flags=re.M)[1:]:
            node_id = block.split("\n", 1)[0].strip()
            if not re.search(r"^\s{4}(command|prompt):", block, re.M):
                continue
            allowed = re.search(r"allowed_tools:\s*\[(.*?)\]", block, re.S)
            if not allowed:
                continue
            tools = allowed.group(1)
            if "Read" not in tools and "Glob" not in tools and "Grep" not in tools:
                continue  # no filesystem, nothing to deny
            if "holdout" not in block:
                fail(
                    "holdout deny",
                    f"{wf.stem}/{node_id} can read files and has no holdout deny list -- "
                    f"it can open the assertions it will be judged against",
                )


def main(argv: list[str]) -> int:
    root = HOME / "template"
    if "--repo" in argv:
        root = Path(argv[argv.index("--repo") + 1]).resolve()

    print(f"auditing {root}\n")

    check_all_scripts_parse(root)
    check_node_outputs(root)
    check_emitting_scripts(root)
    check_scoped_grants(root)
    check_yaml_booleans(root)
    check_state_labels(root)
    check_markers(root)
    check_no_freelance_writes(root)
    check_holdout_isolation(root)
    check_deny_lists(root)

    fails = [f for f in FINDINGS if f[0] == "FAIL"]
    warns = [f for f in FINDINGS if f[0] == "warn"]

    for sev, check, detail in FINDINGS:
        mark = "FAIL" if sev == "FAIL" else "warn"
        print(f"[{mark}] {check}: {detail}")

    if not FINDINGS:
        print("No findings. The machinery's cross-file invariants hold.")
    print(f"\n{len(fails)} failing, {len(warns)} warnings")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
