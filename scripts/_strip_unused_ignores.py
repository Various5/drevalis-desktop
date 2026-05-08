"""One-off: parse mypy output and strip every `# type: ignore[...]` that
mypy reports as unused-ignore. Run from the repo root."""

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

    # Lines look like:
    #   src\drevalis\foo\bar.py:42: error: Unused "type: ignore" comment  [unused-ignore]
    pattern = re.compile(r"(src[\\/].+?\.py):(\d+):.*\[unused-ignore\]")

    to_strip: dict[str, set[int]] = {}
    for line in result.stdout.splitlines():
        m = pattern.search(line)
        if m:
            fname = m.group(1).replace("\\", "/")
            to_strip.setdefault(fname, set()).add(int(m.group(2)))

    print(f"files: {len(to_strip)}  lines: {sum(len(v) for v in to_strip.values())}")

    # Match a trailing `# type: ignore` or `# type: ignore[foo,bar]`,
    # including any preceding whitespace (but keep the newline).
    strip_re = re.compile(r"[ \t]*#[ \t]*type:[ \t]*ignore(?:\[[^\]]*\])?[ \t]*$")

    changed_files = 0
    for fname, line_nos in to_strip.items():
        path = Path(fname)
        if not path.exists():
            print(f"MISSING: {fname}")
            continue
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        modified = False
        for ln in sorted(line_nos):
            idx = ln - 1
            if idx >= len(lines):
                continue
            original = lines[idx]
            # Strip the newline before regex, add it back after.
            had_newline = original.endswith("\n")
            stripped = original.rstrip("\n")
            new_line = strip_re.sub("", stripped)
            if had_newline:
                new_line += "\n"
            if new_line != original:
                lines[idx] = new_line
                modified = True
        if modified:
            path.write_text("".join(lines), encoding="utf-8")
            changed_files += 1
            print(f"  patched {fname}: {len(line_nos)} line(s)")

    print(f"done — {changed_files} file(s) modified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
