"""Dead-skill-path check.

Walks every ``.claude/skills/**/SKILL.md`` file, extracts path-shaped
strings that look like references into the repo (e.g. ``tools/foo``,
``pixie/bar.py``, ``.build/baz``, ``pixie/templates_scaffold/qux``),
and verifies each one resolves to an existing file or directory on
disk. Exits 1 with the offending file:path on failure.

Used by ``.github/workflows/ci.yml``; safe to run locally:

    python tools/ci/check_skill_paths.py

Designed for the master-prompt section 9.4 audit. The matcher is a
deliberately narrow heuristic (only paths rooted in known top-level
folders) to avoid flagging Markdown prose like ``2026/05/18``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Resolve repo root: <repo>/tools/ci/check_skill_paths.py -> <repo>
ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = ROOT / ".claude" / "skills"

# Only flag paths that start with one of these known top-level segments.
# Keeps the matcher away from URLs, dates, ``2.1.3`` style version refs,
# and arbitrary fenced-code snippets.
PATH_RE = re.compile(
    r"(?:\.build|tools|pixie/templates_scaffold|pixie)/[A-Za-z0-9_./-]+"
)


def main() -> int:
    if not SKILLS_ROOT.exists():
        print(f"no skills dir at {SKILLS_ROOT.relative_to(ROOT)}; nothing to check.")
        return 0

    errors: list[str] = []
    for skill_md in sorted(SKILLS_ROOT.glob("**/SKILL.md")):
        try:
            text = skill_md.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"{skill_md.relative_to(ROOT)}: unreadable ({exc})")
            continue

        seen: set[str] = set()
        for match in PATH_RE.finditer(text):
            candidate = match.group(0)
            # Strip a trailing punctuation char that the regex may have
            # swallowed from prose like ``see pixie/foo.py.`` -> ``pixie/foo.py``.
            while candidate and candidate[-1] in ".,);:":
                candidate = candidate[:-1]
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)

            target = ROOT / candidate
            if not target.exists():
                errors.append(
                    f"{skill_md.relative_to(ROOT)}: dead path {candidate}"
                )

    if errors:
        print("\n".join(errors))
        print(f"\n{len(errors)} dead path(s) found.", file=sys.stderr)
        return 1

    print("All skill paths resolve.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
