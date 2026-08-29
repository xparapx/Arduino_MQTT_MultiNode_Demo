"""Claude Code PreToolUse hook: run the test suite before any `git commit`.

Reads the tool call from stdin (JSON), ignores everything that is not a
`git commit`, otherwise runs `uv run pytest -q` inside hub/ and blocks the
commit (exit 2) when tests fail. Stdout/stderr go back to Claude.
"""

import json
import os
import re
import subprocess
import sys


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    cmd = (data.get("tool_input") or {}).get("command", "")
    if not re.search(r"\bgit\s+commit\b", cmd):
        return 0
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    hub = os.path.join(root, "hub")
    r = subprocess.run(
        ["uv", "run", "--directory", hub, "pytest", "-q", "-x", "-p", "no:cacheprovider"],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        sys.stderr.write("pre-commit hook: tests failed, commit blocked\n")
        sys.stderr.write(r.stdout[-3000:] + r.stderr[-1500:])
        return 2
    last = (r.stdout.strip().splitlines() or ["ok"])[-1]
    print(f"pre-commit hook: tests passed ({last})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
