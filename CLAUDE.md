# CLAUDE.md

This workspace is the **data directory of a live Red-DiscordBot instance**, not a source repo. Most development work means editing the four custom cogs under `data/cogs/CogManager/cogs/`.

## Runtime environment

- **Red-DiscordBot 3.5.24**, **discord.py 2.7.1**, **Python 3.11**, running on **Linux in Docker**. The venv was created at `/data/venv` and `config.json` names the instance `docker` with `DATA_PATH=/data`, so `data/` here is the container's `/data` mount. The layout (`venv/.redbotversion`, `.pyversion`) matches the `phasecorex/red-discordbot` image.
- Storage driver is **JSON**: every cog's config lives in `data/cogs/<CogName>/settings.json`.
- Command prefix is `!`. Docstrings and help text use `[p]` for the prefix, which is the Red convention.
- The bot **cannot be run from this Windows machine**. `data/venv` holds Linux binaries, so don't run, modify or reinstall anything in it. Local Python is good for syntax checks (`python -m py_compile <file>`). For behavior tests, install `discord.py==2.7.1` and `tzdata` into a scratch folder with `pip install --target`, and stub `redbot` (Config, `checks`, the Red-only bot methods). Real discord.py views, `DynamicItem`s and command invocation then work offline.
- **Test changes in Discord**: after editing a cog, run `!reload <cogname>` (for example `!reload gamemanager`). If a cog needs new pip dependencies, add them to `requirements` in its `info.json` and install them in the container with `!pipinstall <pkg>`, or ask the user to do it.
- **Git:** the workspace root is a git repo (remote `https://github.com/bradqui/Red`, private). `.gitignore` is a whitelist that tracks only the custom cogs, `CLAUDE.md`, and `backups/`. The server deploys by running `git pull` in the folder that holds `data/`. Everything else under `data/` is runtime state and is deliberately untracked: the venv, Downloader libs, third-party repos, logs, and every `settings.json`, which hold the bot token, API keys, and user and server IDs. To track a new custom cog, add a `!` line for it in `.gitignore`. Never commit `settings.json` files.

## Directory layout

```
data/
  config.json                 # instance config (docker paths, JSON storage)
  core/settings.json          # core bot config: TOKEN, prefix, loaded packages, shared API keys (SECRET)
  core/logs/latest.log        # current run's log; red-part*.log are rotated history
  cogs/
    CogManager/cogs/<cog>/    # install path: every non-core cog that gets loaded lives here
    RepoManager/repos/<repo>/ # git clones of third-party cog repos (Downloader source)
    Downloader/lib/           # pip packages installed for cogs (shared, on sys.path)
    <CogName>/settings.json   # per-cog Config data (named by the cog class, not the package)
  venv/                       # container's Python venv; never touch
```

## Custom cogs (ours, safe to edit)

None of these are tracked by Downloader. Two first-run steps are still needed on the server:
- The `claude` cog (new 2026-11-02) needs `!pipinstall anthropic` and `!load claude`; it isn't in the loaded-packages list below yet.
- GameManager (rewritten 2026-11-03) needs `!pipinstall tzdata` before `!reload gamemanager`. Each one is a single module plus `__init__.py` with `async def setup(bot): await bot.add_cog(...)`.

| Package | Cog class / data dir | Config identifier | Purpose |
|---|---|---|---|
| `buttongreeter` | `ButtonGreeter` | `8473829102` | Welcome flow on `on_member_join`: alliance/role buttons → nickname tag `[TAG] Name` → rules agreement → rules role. Commands: `!bg …`, `!changerole`, and the mod-role-gated `!forceclass` / `!forcerulesremove`. Errors go to a configured admin channel. |
| `censord` | `Censord` | `8473829201` | Word filter with `off/low/high` levels. Word lists are **CSV files** in `data/cogs/Censord/{low,high}.csv` (single row, `*` = wildcard; without one the word gets `\b` boundaries). Has a per-channel override, include/exclude strategy, and a threshold (N hits in T seconds) that triggers delete/kick/ban. Commands: `!censor …`. Mods and admins are immune. |
| `gamemanager` | `GameManager` | `8675309420` | Per-guild game library (owned/installed/ranks; installing implies owning), tick-box pickers, shared-game finder, `lfg` pings, scheduled play sessions with reminders, and votes with rank tie-breaks. Text commands live under `!games` (aliases `game`, `gm`); the slash group is `/games` (needs `!slash enable games` + `!slash sync`). Needs `tzdata` for timezones. Has a full `README.md`. |
| `claude` | `ClaudeChat` | `5528341907` | **Main AI chat** via the `anthropic` SDK (async client). `!ai` (aliases `chat`, `ask`, `g`) is the shared per-channel conversation, `!myai` the private per-user one, and `!aithread` starts a thread. Replying to any AI answer continues that conversation, and so does @mentioning the bot in an AI thread. Claude reads attached images, PDFs and text files, can search the web (citations become a "Sources" footer), tracks usage and estimated cost, enforces optional per-user daily limits, and supports a per-server persona. Settings live under `!claude …`. The API key is Red's shared token `anthropic`/`api_key` (`!set api anthropic api_key,<key>`). Default model is `claude-sonnet-5-5` at effort `low`. Images take two paths, and both need the Gemini cog loaded. **Fast path:** prompts matching `IMAGE_NEW_TRIGGERS` ("draw…", "image of…") go straight to Gemini with no Claude tokens, and so do `IMAGE_UPDATE_TRIGGERS` ("make it…") right after an image. **Fallback:** a `generate_image` client tool lets Claude hand off image requests the patterns miss. **Bot guide:** `!guide` and plain @mentions outside AI threads use Haiku to answer "how do I…" questions and to run commands for the asker. The model is set by `guide_model` (`!claude guidemodel`). It speaks in the server persona's voice, but its accuracy rules take priority. Admins toggle @mentions with `!claude guidementions` and command-running with `!claude guideactions`. There are deliberately no `howto`/`howdoi` aliases, so people phrase the whole request and it's clear whether they want an explanation or an action. |
| `gemini` | `GeminiChat` | `9283748291` | **Image generation only** since 2026-11-02 (the chat version is in `backups/gemini-2026-11-02/`). `!draw <prompt>` and `!draw edit <changes>`, `!gemini setkey/list/settings/model/channelmodel`. Exposes `generate_image(prompt, session_key, reply_target, *, channel, user, new)`, which the Claude cog calls. **Keep that signature stable.** The API key is in Config global `api_key`. |

Quirks to know:
- **typing_extensions:** both AI cogs' `__init__.py` swap in a newer `typing_extensions` before importing their SDK, because pydantic needs `typing_extensions.Sentinel` and the venv's copy (4.13.2) lacks it. Red appends `Downloader/lib` to the *end* of `sys.path`, so the old venv copy wins otherwise. Gemini vendors a copy in `gemini/lib/`; Claude loads `Downloader/lib/typing_extensions.py` directly.
- **Claude cog design:**
  - Conversation history is stored as plain user/assistant **text** turns with no thinking blocks, so trimming old turns is safe under Anthropic's preserved-thinking rules.
  - **Persona:** the server's `persona` is used first, then its saved `default_persona` (`!claude defaultpersona <text|current|clear>`; up to `MAX_PERSONA_CHARS` = 3,000 characters, or attach a `.txt` file since Discord messages stop at 2,000), then the built-in `DEFAULT_PERSONA` (see `_persona()`). `!claude persona reset` clears `persona`, so the saved default takes over.
  - **Model choice:** `!claude mymodel` is admin-only. A personal model counts only while it's in `allowed_models`; disallowing a model sends those private chats back to the default. Channel models (mods) are unaffected. Fable isn't in `MODELS`.
  - In every user turn, the speaker's display name comes first (`Name: message`).
  - Mentions are passed through raw, with a note: `_mention_note` adds `(Mentions: <@id> is Name; …)` for the users, roles and channels in the message and in the message it replies to. The bot can write `<@id>` to mention someone. Replies use `NO_MENTIONS`, so the name is highlighted but nobody is pinged. Image prompts for Gemini and re-seeded thread history use plain names instead (`_readable` / `clean_content`).
  - Sessions live in RAM, keyed `CHANNEL_<id>`, `THREAD_<id>` or `USER_<id>`. They reset on reload or after `idle_minutes`.
  - After a restart, AI threads re-seed their context from recent thread history. The reply-to-continue index (`_answers`) is in RAM and isn't rebuilt, so replies to answers from before a restart are ignored.
  - Requests use the beta Messages API with `fallbacks: "default"` (refusal fallback), top-level `cache_control`, and the `web_search_20260209` tool when enabled.
  - **Bot guide:** `_command_catalog` builds a fresh, sorted reference of every command on every request: each command's usage, aliases, who can run it (from `requires`, inheriting from parent group or cog), and its help capped at 600 characters, with `[p]` and `[botname]` filled in. It skips hidden commands, disabled commands and cogs disabled in the guild. Bot-owner-only commands are included only when the bot owner asks. The catalog is the system prompt, with its own cache breakpoint. Expect roughly 20–25K tokens for members and about 45K for the owner, all from cache after the first question. Each user has one guide session, `GUIDE_<user id>`, keeping 10 messages and resetting after 15 idle minutes. Anyone who replies to a guide answer continues their *own* guide session. Guide questions count toward usage but not the daily limit. The main `!ai` prompt tells Sonnet it doesn't know the commands and should point people to `!guide`.
  - **Replies to the bot's other messages:** this covers anything not in `_answers`, such as GameManager announcements or AI answers from before a restart. These replies also go to the guide when `guide_mentions` is on, with the replied-to message quoted. The prompt lets Haiku answer `[silent]` (`GUIDE_SILENT`) for replies meant for other people. In that case nothing is posted, no typing indicator is shown, and nothing is kept in history.
  - **Guide actions:** Haiku gets a strict `run_commands` tool (`message`, `commands[]`). As with images, no `tool_result` is sent back; history gets a text note such as `[Ran: …]`.
    - `_plan_actions` resolves each command with `bot.get_command` (longest prefix).
    - It refuses unknown and hidden commands, the guide/AI commands themselves, and bot-owner-only commands.
    - It checks each command with Red's `can_run(ctx, check_all_parents=True)`, using a copy of the asker's message.
    - `_run_actions` invokes each command in order as the asker (`bot.invoke`), waiting at most 20 s per step.
    - Any command with a requirement label (mod/admin/permission/custom) needs the asker to press **Run** first (`ActionConfirmView`).
  - **Extension hooks for other cogs:**
    - A check predicate with a `requirement` attribute (e.g. GameManager's `game_admin()`, `"game admin"`) shows up as "(game admin only)" in the catalog and triggers confirmation.
    - A cog method `async guide_member_roles(member) -> List[str]` adds roles to the asker's permission label.
    - **Read-only lookups:** a cog with `guide_tools() -> List[tool dict]` and `async guide_call_tool(name, args, asker) -> str` offers lookup tools.
      - `_guide_call` runs a loop of up to 3 rounds per answer: tool_use → tool_result → final answer. The tool blocks stay within that turn; history stores only the final text.
      - A `run_commands` call ends the loop.
      - GameManager offers `games_library`, `games_game` and `games_activity`. Prefix new tool names with the cog's name to avoid clashes.
      - The AI chat (`_call_claude`) is offered the same lookups, through the same `_run_lookups`, alongside web search and image calls. Text written before a lookup is dropped, the same way as for web searches.
  - When Claude calls `generate_image` (strict schema: `prompt`, `edit`), the cog runs it through Gemini and **does not send a tool_result back**. This saves a second API call. History records a text note such as `[Generated an image: "…"]` instead of tool blocks, so it stays text-only. Pricing for the usage estimates is in the `MODELS` table in `claude.py`; update it if prices change.
- **Command name conflicts:** the old chat Gemini and the Claude cog both define `ai`/`myai`/`aithread`. Only the image-only Gemini can be loaded alongside Claude.
- `buttongreeter` views use `timeout=None` but aren't registered as persistent views, so buttons on welcome messages sent before a restart or reload stop working.
- **GameManager internals:**
  - **Persistent buttons:** session, vote, request and install buttons are discord.py `DynamicItem`s (custom IDs `gm:s:<action>:<sid>`, `gm:v:<vid>:<gid>`, `gm:r:<action>:<rid>`, `gm:i:<rid>`), registered in `cog_load`. They keep working after restarts. Buttons posted by the pre-2026-11 version used static IDs and are dead.
  - **Vote timers:** they live in `self.vote_tasks`. `_resume_votes` reschedules them from each vote's `ends_at` on load.
  - **Background loop:** a 1-minute `tasks.loop` (`session_loop`) sends reminders and start pings, and ends sessions 12 h after start or creation.
  - **Writes:** all go through `async with config…() as x` (Red locks these) so simultaneous clicks don't lose updates.
  - **Name lookups:** they use `resolve_game`, which matches exactly first and accepts a partial match only if it's unique.
  - **One implementation, two front ends:** shared methods take a `Target` (a Context or an Interaction), so text and slash commands reuse the same code.
  - **Game-admin commands:** use the `game_admin()` check, which raises `UserFeedbackCheckFailure` so the user sees why.
  - **New game names:** they pass through `checked_names` before a request or add (`!games request`, `/games request`, `!games admin add`, and the Request/Add buttons).
    - `suggest_titles` tries, in order: a library near-match (difflib), Steam's exact-name store search (`steam_exact_title`, no key), then the Claude cog's public `find_game_title(name, member)`.
    - Fixes that only change capitalization or symbols apply silently. Real spelling changes need the person to confirm (`NameCheckView`).
    - Games and requests store `steam_appid` when one is known.
  - **`find_game_title`** (Claude cog) tries Haiku with `web_search_20260209`, then Haiku with `web_search_20250305`, then Sonnet (`TITLE_SEARCHERS`). It remembers the first option the API accepts, and it reports through a strict `report_title` client tool without sending a tool_result back.
- `censord` reads guild and channel Config on every message.
- `data/cogs/ButtonGreeter/` holds an **older, stale copy** of `buttongreeter.py`, `__init__.py` and `info.json` next to its `settings.json`. That copy isn't loaded; the live code is in `CogManager/cogs/buttongreeter/`. Don't edit the stale copy by mistake.
- The `info.json` files have placeholder authors (`"YourName"`, `"Claude"`); the real author is Quillshot.

## Third-party cogs (do NOT edit in place)

Installed via Downloader. Any `!cog update` overwrites their files in `CogManager/cogs/`, and the matching sources in `RepoManager/repos/` are git clones:

`antispam` (flare-cogs), `roletools` (Trusty-cogs), `autoroler` (Dav-cogs), `autoroom` (pcxcogs), `system` (vex-cogs), `easytranslate` (crab-cogs), `chatchart` (aikaterna-cogs), `clearchannel` + `consolelogs` (aaa3a-cogs, which need the `AAA3A_utils` lib), `customhelp` (npc-cogs).

To change one of these, fork it into a new, differently named package under `CogManager/cogs/` rather than patching the Downloader-managed copy. The repo clones are a good reference for idiomatic Red cog code.

Loaded packages, from `core/settings.json`: admin, alias, cleanup, customcom, downloader, filter, general, modlog, mutes, permissions, trivia, warnings, mod (core), plus antispam, autoroom, system, easytranslate, censord, gamemanager, buttongreeter, chatchart, clearchannel, consolelogs, customhelp, gemini. `roletools` and `autoroler` are installed but **not loaded**.

## Coding conventions for cogs here

- Use Red's `Config` for all persistence: `Config.get_conf(self, identifier=<int>, force_registration=True)`, then `register_guild/channel/user/global`, and `async with self.config.guild(g).thing() as x:` for mutations. **Never change an existing cog's identifier**, because that orphans all of its saved data. For non-Config files, use `redbot.core.data_manager.cog_data_path(self)` (as Censord does).
- Permission checks use `redbot.core.checks` / `commands` decorators (`admin_or_permissions`, `mod_or_permissions`, `is_owner`, `guild_only`), plus each cog's own configurable admin/mod role.
- UI is built with `discord.ui.View` / `Button` / `Modal`; interaction errors are reported ephemerally.
- Match the existing style: section-divider comments, emoji-prefixed status messages (✅ ❌ ⚠️), embeds for settings displays.
- Prefer `logging.getLogger("red.<cogname>")` over `print`. Output lands in `core/logs/`.
- Clean up background tasks in `cog_unload`.
- When adding a dependency, list it in the cog's `info.json` `requirements`. Packages land in `data/cogs/Downloader/lib/`.

## Secrets (never print, log, or copy out)

- `data/core/settings.json` → `GLOBAL.token` (Discord bot token) and `SHARED_API_TOKENS` (e.g. openweathermap)
- `data/cogs/GeminiChat/settings.json` → Gemini `api_key`
- The Anthropic key is in `core/settings.json` under `SHARED_API_TOKENS.anthropic`

When inspecting these files, redact secrets programmatically instead of catting the whole file.

## Editing config data

Don't hand-edit any `settings.json` while the bot is running: the JSON driver keeps data in memory and overwrites manual edits. Change settings through bot commands, or stop the container first. The Censord CSVs are the exception; edit them on disk, then run `!censor reload`.
