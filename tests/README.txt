Offline tests for ButlerBot's custom cogs. They run without Discord or Red: harness.py stubs Red (Config, checks, the
bot), uses real discord.py, and fakes guilds, members, channels and interactions. GitHub runs them on every push
(.github/workflows/tests.yml, Python 3.11 like the live bot).

Setup, once:
    python -m pip install -r tests/requirements.txt
  (or install into tests/pylibs with --target; harness.py adds that folder to the path if it exists)

Run them:
    python tests/run_all.py                 every test file, one at a time, each with a time limit
    python tests/run_all.py parlor estate   only files whose names contain one of these words
    python tests/test_parlor.py             one file; it prints "N/M checks passed" and any FAIL lines

Each file also checks every card it sends against Discord's limits and prints LAYOUT PROBLEMS when one is over.

eval_unified.py is different: it's a live evaluation of the AI chat against the real Anthropic API and costs money
(about $0.20-0.65 a run). It reads the key from ~/.butlerbot-eval-key, uses ./apilibs, and never runs in CI.

Cogs are loaded from ../data/cogs/CogManager/cogs (harness.COGS), so the repository folder can be renamed freely.
