"""One-off: for each mypy type-arg error, parametrize the offending
annotation in-place.

Rules used (mechanical, conservative):
  - Bare ``dict`` in an annotation → ``dict[str, Any]``
  - Bare ``list`` in an annotation → ``list[Any]``

Only changes tokens that are clearly annotation contexts (after ``:``,
``->``, inside ``[...]`` of another generic, or as the base of ``Dict[...]``
style — which we don't need here since mypy complains about the bare ones).
We identify each problem site by line number from mypy's output and rewrite
just that line.

If the file didn't already import ``Any``, we add ``from typing import Any``
near the top (after ``from __future__`` if present).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


def main() -> int:
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "-p", "drevalis", "--no-strict-optional"],
        capture_output=True,
        text=True,
        check=False,
    )

    # Matches:
    #   src\...\foo.py:123: error: Missing type arguments for generic type "dict"  [type-arg]
    pattern = re.compile(
        r'(src[\\/].+?\.py):(\d+):.*Missing type (?:arguments|parameters) for generic type "(dict|list)".*\[type-arg\]'
    )

    hits: dict[str, list[tuple[int, str]]] = {}
    for line in result.stdout.splitlines():
        m = pattern.search(line)
        if m:
            fname = m.group(1).replace("\\", "/")
            hits.setdefault(fname, []).append((int(m.group(2)), m.group(3)))

    print(f"files: {len(hits)}  sites: {sum(len(v) for v in hits.values())}")

    # Replacement patterns. Use negative lookahead / lookbehind to avoid
    # matching:
    #   - identifiers (so ``my_dict`` stays intact)
    #   - already-parametrized (``dict[...]``)
    #   - module refs (``foo.dict``) — not applicable here
    dict_re = re.compile(r"(?<![A-Za-z0-9_\.])dict(?!\s*[\[A-Za-z0-9_])")
    list_re = re.compile(r"(?<![A-Za-z0-9_\.])list(?!\s*[\[A-Za-z0-9_])")

    def needs_any_import(source: str) -> bool:
        return "from typing import" in source and not re.search(
            r"from typing import[^\n]*\bAny\b", source
        )

    def add_any_import(source: str) -> str:
        """Append ``Any`` to the first ``from typing import`` found."""
        new = re.sub(
            r"(from typing import\s+)(.+)",
            lambda m: m.group(1)
            + (m.group(2) if "Any" in m.group(2) else "Any, " + m.group(2)),
            source,
            count=1,
        )
        return new

    def add_any_import_fresh(source: str) -> str:
        """No ``from typing import`` exists — add one after future imports."""
        # After the ``from __future__ ...`` line, if present; otherwise after
        # the module docstring.
        lines = source.splitlines(keepends=True)
        insert_at = 0
        for i, ln in enumerate(lines):
            if ln.startswith("from __future__"):
                insert_at = i + 1
                break
        # Skip blank lines after the future import
        while insert_at < len(lines) and lines[insert_at].strip() == "":
            insert_at += 1
        lines.insert(insert_at, "from typing import Any\n")
        # Ensure a blank line separator
        if insert_at + 1 < len(lines) and lines[insert_at + 1].strip() != "":
            lines.insert(insert_at + 1, "\n")
        return "".join(lines)

    changed_files = 0
    for fname, sites in hits.items():
        path = Path(fname)
        if not path.exists():
            print(f"MISSING: {fname}")
            continue
        source = path.read_text(encoding="utf-8")
        orig_source = source
        lines = source.splitlines(keepends=True)

        unique_lines: dict[int, set[str]] = {}
        for ln, kind in sites:
            unique_lines.setdefault(ln, set()).add(kind)

        for ln, kinds in unique_lines.items():
            idx = ln - 1
            if idx >= len(lines):
                continue
            line = lines[idx]
            new = line
            if "dict" in kinds:
                new = dict_re.sub("dict[str, Any]", new)
            if "list" in kinds:
                new = list_re.sub("list[Any]", new)
            lines[idx] = new

        new_source = "".join(lines)
        if new_source == orig_source:
            continue

        # Make sure Any is importable
        if "dict[str, Any]" in new_source or "list[Any]" in new_source:
            if not re.search(r"\bfrom typing import[^\n]*\bAny\b", new_source):
                if "from typing import" in new_source:
                    new_source = add_any_import(new_source)
                else:
                    new_source = add_any_import_fresh(new_source)

        path.write_text(new_source, encoding="utf-8")
        changed_files += 1
        print(f"  patched {fname}: {len(sites)} site(s)")

    print(f"done — {changed_files} file(s) modified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
