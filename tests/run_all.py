#!/usr/bin/env python3
"""
Run every test file (tests/test_*.py), one at a time, each in its own process with a time limit.

A file passes when it exits cleanly, prints "N/N checks passed" (or "N/N passed"), and reports no FAIL lines and no
LAYOUT PROBLEMS (cards over Discord's limits). Exits non-zero if any file doesn't pass, for CI.

    python tests/run_all.py                  # everything
    python tests/run_all.py parlor caption   # only files whose names contain one of these words

eval_unified.py isn't a test file: it calls the real Anthropic API and costs money, so it never runs here.
"""

import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TIMEOUT = 300
COUNT = re.compile(r"^(\d+)/(\d+) (?:checks )?passed\s*$", re.M)
PASSED_FAILED = re.compile(r"^(\d+) passed, (\d+) failed\s*$", re.M)   # test_butlerui.py's style


def run(path: Path) -> tuple:
    """(ok, summary, output) for one test file."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "MPLBACKEND": "Agg"}
    started = time.monotonic()
    try:
        done = subprocess.run([sys.executable, path.name], cwd=HERE, env=env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=TIMEOUT)
    except subprocess.TimeoutExpired as e:
        return False, f"timed out after {TIMEOUT} s", (e.stdout or "") + (e.stderr or "")
    output = (done.stdout or "") + (done.stderr or "")
    seconds = time.monotonic() - started
    counts = COUNT.findall(done.stdout or "") or [(p, int(p) + int(f)) for p, f in PASSED_FAILED.findall(done.stdout or "")]
    failed = [line for line in output.splitlines() if line.startswith("FAIL")]
    layout = "LAYOUT PROBLEMS" in output
    if done.returncode != 0:
        return False, f"crashed (exit {done.returncode})", output
    if not counts:
        return False, "printed no result line", output
    passed, total = (int(n) for n in counts[-1])
    if failed or layout or passed != total:
        why = f"{passed}/{total} passed" + (" · layout problems" if layout else "")
        return False, why, output
    return True, f"{passed}/{total} in {seconds:.0f} s", output


def main(argv: list) -> int:
    words = [w.lower() for w in argv[1:]]
    files = sorted(p for p in HERE.glob("test_*.py") if not words or any(w in p.name.lower() for w in words))
    if not files:
        print("No test files matched.")
        return 1
    bad = []
    for path in files:
        ok, summary, output = run(path)
        print(f"{'ok  ' if ok else 'FAIL'} {path.name:<28} {summary}", flush=True)
        if not ok:
            bad.append(path.name)
            tail = [line for line in output.splitlines() if line.strip()][-25:]
            print("\n".join(f"     | {line}" for line in tail), flush=True)
    print(f"\n{len(files) - len(bad)} of {len(files)} test files passed.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
