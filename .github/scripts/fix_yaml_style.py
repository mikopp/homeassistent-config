#!/usr/bin/env python3
"""Fix YAML style issues without changing content.

Applies three text-level fixes to every .yaml/.yml file:
  - Convert CRLF line endings to LF
  - Remove trailing whitespace from each line
  - Ensure the file ends with exactly one newline
"""

import glob
import os
import sys


def fix_file(path: str) -> bool:
    with open(path, "rb") as f:
        original = f.read()

    content = original.replace(b"\r\n", b"\n").replace(b"\r", b"\n")

    lines = content.split(b"\n")
    lines = [line.rstrip() for line in lines]
    content = b"\n".join(lines)

    content = content.rstrip(b"\n") + b"\n"

    if content != original:
        with open(path, "wb") as f:
            f.write(content)
        return True
    return False


def main() -> None:
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    files = []
    for pattern in ["**/*.yaml", "**/*.yml"]:
        files.extend(glob.glob(os.path.join(root, pattern), recursive=True))

    files = sorted(f for f in files if "/.git/" not in f.replace(os.sep, "/"))

    changed = [f for f in files if fix_file(f)]

    if changed:
        print(f"Fixed {len(changed)} file(s):")
        for f in changed:
            print(f"  {f}")
    else:
        print("All files already clean.")


if __name__ == "__main__":
    main()
