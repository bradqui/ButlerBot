# CLAUDE.md

This workspace is the **data directory of a live Red-DiscordBot instance**, not a source repo. Most development work means editing the four custom cogs under `data/cogs/CogManager/cogs/`.

## Runtime environment

- **Red-DiscordBot 3.5.24**, **discord.py 2.7.1**, **Python 3.11**, running on **Linux in Docker**. The venv was created at `/data/venv` and `config.json` names the instance `docker` with `DATA_PATH=/data`, so `data/` here is the container's `/data` mount. The layout (`venv/.redbotversion`, `.pyversion`) matches the `phasecorex/red-discordbot` image.
- Storage driver is **JSON**: every cog's config lives in `data/cogs/<CogName>/settings.json`.
- Command prefix is `!`. Docstrings and help text use `[p]` for the prefix, which is the Red convention.
- The bot **cannot be run from this Windows machine**. `data/venv` holds Linux binaries, so don't run, modify or reinstall anything in it. Local Python is good for syntax checks (`python -m py_compile <file>`). For behavior tests, install `discord.py==2.7.1` and `tzdata` into a scratch folder with `pip install --target`, and stub `redbot` (Config, `checks`, the Red-only bot methods). Real discord.py views, `DynamicItem`s and command invocation then work offline.
- **Test changes in Discord**: after editing a cog, run `!reload <cogname>` (for example `!reload gamemanager`). If a cog needs new pip dependencies, add them to `requirements` in its `info.json` and install them in the container with `!pipinstall <pkg>`, or ask the user to do it.
- **Git:** the workspace root is a git repo (remote `https://github.com/bradqui/ButlerBot`, renamed from `Red` on 2026-11-04; old URLs redirect; **public** since 2026-11-04, MIT licensed; the server can pull over HTTPS with no key). Because the repo is public, **anything committed is published**: re-check that no secrets, IDs or private server details get tracked. `.gitignore` is a whitelist that tracks only the custom cogs, the root docs (`CLAUDE.md`, `README.md`, `LICENSE`), the handbook in `docs/` and `tools/`. The server deploys by running `git pull` in the folder that holds `data/`. Everything else under `data/` is runtime state and is deliberately untracked: the venv, Downloader libs, third-party repos, logs, and every `settings.json`, which hold the bot token, API keys, and user and server IDs. To track a new custom cog, add a `!` line for it in `.gitignore`. Never commit `settings.json` files.

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
| `activitystats` | `ActivityStats` | `7734152096` | Activity stats (new 2026-11-04; needs `!load activitystats`). Counts go to **SQLite** at `data/cogs/ActivityStats/stats.db`, not Config: hourly message counts per (guild, channel, user), voice visits, games from "Playing" presence, joins/leaves, command uses, unmet guide questions and game-session attendance. Settings (exclusions, game tracking, digest) are in Config. Threads count toward their parent channel. Channel arguments go through `ChannelArg` (mention, ID or name); a name several channels share, like a text and a voice channel, opens a `ChannelPicker`. Messages are buffered in RAM and flushed every 60 s. Each report is one `report_*` method returning a `Report` (title, lines, optional chart callable drawn with matplotlib's `Figure` API in a worker thread). Commands render it as an embed, and the `stats_report` guide tool renders it as plain text via `_plain`. Member reports only show channels the viewer can see; admin reports (`!stats admin …`, or tool reports in `ADMIN_REPORTS`) need admin or manage server. `!stats ignoreme` deletes a member's rows and stops tracking. `!stats admin backfill <days>` reads channel history from before tracking started (messages only). |
| `speakup` | `SpeakUp` | `6029481735` | **The bot chiming in** (new 2026-11-04; needs `!load speakup`). Every feature can be switched off: per server with `!speakup feature`, per channel with `!speakup off` (`quiet_channels`), and per person with `!speakup me off`. All of them check `allowed()`. Nothing in it pings. **Times** (`find_time`): am/pm and HH:MM times always count; a bare "at 9" counts only with planning words (`PLANNING_RE`) and is read as PM unless the message says "morning". The time is read in the author's GameManager timezone. The bot adds a 🕘 reaction (5-min channel cooldown); a click replies with Discord timestamps plus a persistent **Schedule a session** button (`sp:sched:<ts>`) that calls GameManager's `post_session`. **Steam links** get a card (no image, since Discord already embeds one) with own/want buttons (`sp:own|want:<appid>`), once per game per channel per 6 h. **Other links** get a 📄 reaction. `summary_links` skips media files, Discord, Steam and known GIF/image hosts. `_article_links` also waits `EMBED_WAIT` s for Discord's link previews and drops links previewed as `image`/`gifv`/`video`. Video sites (YouTube, Vimeo, TikTok…) are in `SKIP_LINK_HOSTS` too, since web fetch can't summarize a video (2026-11-05). a click posts a summary in the channel. The **Summarize link** message context menu (`summarize_menu`, added to `bot.tree` in `cog_load`; it needs `[p]slash enable "Summarize link" message` and `[p]slash sync`) answers the same privately (ephemeral). Both go through `summarize()`, which caches a URL's summary for an hour, and `_summary_allowed()` (10 per person per hour). **Mistakes:** `CommandNotFound`, or an argument-less group given an unknown word (`unknown_subcommand` reads the leftover text, because discord.py clears `subcommand_passed`). It tries `fuzzy_suggestion` (difflib on the first 1–3 words) first, then Claude's `suggest_command`, and replies with a Run-it view. GameManager's `games` group stays quiet when `handles_mistakes(ctx)` is true. **Reminders** are in Config global `reminders`. Relative times are parsed here; absolute ones use GameManager's module `split_when` (via `sys.modules`). A 30 s loop delivers them, falling back to DM. Reaction offers are tracked in RAM for 24 h. A click on an unknown offer, after a reload or restart, re-fetches the message, checks that the bot's own reaction is on it (`me`), and rebuilds the offer from the text (`_rebuild_offer`; times are read as of the message's timestamp). Unexpected errors while answering are logged and reported in the channel instead of failing silently. 🗑️ **Remove** buttons (`RemoveButton`, custom ID `sp:x:<uid>`, formerly labeled Dismiss) delete the reply for everyone, after a private `ConfirmRemoveView`. The person it was for, or anyone with Manage Messages, can use one. It's labeled Remove because people read "Dismiss" as hide-for-me. |
| `butlerfun` | `ButlerFun` | `4418350927` | **AI extras** (new 2026-11-04; needs `!load butlerfun`, plus `!slash enable catchup` and `!slash sync` for `/catchup`). All Claude calls go through the Claude cog's public `complete()`. **Catch-up:** reads up to 400 messages back to the asker's last message and summarizes them with Haiku; `/catchup` is ephemeral and `!catchup` sends a DM. **Judge:** the last 20–60 human messages, ruled on in the persona (Sonnet). **Adventure:** a thread per adventure, listed in guild Config `adventures`. Players' messages are buffered for `ADVENTURE_DEBOUNCE` seconds, then narrated in one turn. The story lives in RAM, keeps `ADVENTURE_HISTORY` (200) messages, and is re-seeded from thread history after a restart. Each adventure's Config entry lists its `players`; their member-Config `adventure_bio` (up to 200 characters, checked by Haiku against `BIO_CHECK` when set) goes into the narrator's system prompt, and the story overrides a bio for that adventure. A refused turn posts `ADVENTURE_DEFLECT` and drops that round's moves. `!adventure stop` writes a final scene; Haiku turns it into a safe, wordless picture description (`FINAL_SCENE_PROMPT`) and Gemini draws it with `quiet=True`, then the thread is archived. **maketrivia** (mods): Claude returns JSON, which is written as YAML into Red's trivia folder (`cog_data_path(raw_name="Trivia")/bb_<topic>.yaml`) so `!trivia bb_<topic>` works at once. `our games` uses the GameManager library. Lists are written in batches of `TRIVIA_BATCH` (25), each prompt listing every question so far, and duplicates are dropped by normalized text. Running it on an existing topic **adds** (10–100 per run, default 30, up to `TRIVIA_LIST_MAX` = 300 per list); `redo` replaces, `show` lists with spoilered answers (a board, sent by DM), and `remove` takes numbers or unique question text. Subcommands carry their own mod check, because the group's isn't applied to them. **guessgame:** picks a library game weighted by owners. Haiku describes a scene without names (rejected if the name leaks), and Gemini draws it in a random `ART_STYLES` style. Gemini posts images without a caption. A `wait_for` loop gives hints at 60 and 120 s and reveals the answer at 180 s; wins are stored per member. |
| `handbook` | `Handbook` | `3357204816` | **Help and docs** (new 2026-11-04). It installs a Red help formatter (`HandbookHelp`) in `cog_load`; Red allows only one, so **unload customhelp first**, or `set_help_formatter` raises and the cog only logs a warning (`!handbook status`). `!help` shows a topic card, `!help <command>` a compact card (usage, aliases, who, subcommands) with a link to its topic page and reference anchor, and `!help <cog>` a list. `TOPICS`, `COG_TOPICS` and `GAME_NIGHT_COMMANDS` map cogs and commands to `docs/` permalinks, so **keep them in step with the pages**. `guide_links()` feeds the butler's prompt (`_handbook_lines` in the Claude cog), so answers end with "More: <url>". `!handbook export` (owner) zips `reference/*.md` built from the live bot: one page per cog, anchors `<qualified-name-with-dashes>`, owner-only commands left out, help wrapped in `{% raw %}`. It also writes `reference/custom-commands.md` from the CustomCommands and Alias configs. Unzip it into `docs/`. `requirement()` duplicates the guide's permission-label logic, and also reads `requires.checks`, where Red's `permissions_check` helpers like `admin_or_can_manage_channel` live (`known_check`). The export skips cogs and commands that a Permissions default rule denies (`denied_by_default`). |
| `buttongreeter` | `ButtonGreeter` | `8473829102` | Welcome flow on `on_member_join`: alliance/role buttons → nickname tag `[TAG] Name` → rules agreement → rules role. Commands: `!bg …`, `!changerole`, and the mod-role-gated `!forceclass` / `!forcerulesremove`. Errors go to a configured admin channel. |
| `censord` | `Censord` | `8473829201` | Word filter with `off/low/high` levels. Word lists are **CSV files** in `data/cogs/Censord/{low,high}.csv` (single row, `*` = wildcard; without one the word gets `\b` boundaries). Has a per-channel override, include/exclude strategy, and a threshold (N hits in T seconds) that triggers delete/kick/ban. Commands: `!censor …`. Mods and admins are immune. |
| `gamemanager` | `GameManager` | `8675309420` | Per-guild game library (owned/installed/ranks; installing implies owning), tick-box pickers, a step-by-step profile setup (`newprofile`), shared-game finder, `lfg` pings, scheduled and weekly-recurring play sessions with reminders and Discord events, wishlists with Steam sale alerts, and votes with rank tie-breaks. Text commands live under `!games` (aliases `game`, `gm`); the slash group is `/games` (needs `!slash enable games` + `!slash sync`). Needs `tzdata` for timezones. Has a full `README.md`. |
| `claude` | `ClaudeChat` | `5528341907` | **Main AI chat** via the `anthropic` SDK (async client). `!ai` (aliases `chat`, `ask`, `g`) is the shared per-channel conversation, and `!aithread` starts a thread. (`!myai`, the per-person conversation, was removed on 2026-11-05 as unused, along with `!claude mymodel` and `!gemini model`; their Config user keys are still registered but unused.) Replying to any AI answer continues that conversation, and so does @mentioning the bot in an AI thread. Claude reads attached images, PDFs and text files, can search the web (citations become a "Sources" footer), tracks usage and estimated cost, enforces optional per-user daily limits, and supports a per-server persona. Settings live under `!claude …`. The API key is Red's shared token `anthropic`/`api_key` (`!set api anthropic api_key,<key>`). Default model is `claude-sonnet-5-5` at effort `low`. Images take two paths, and both need the Gemini cog loaded. **Fast path:** prompts matching `IMAGE_NEW_TRIGGERS` ("draw…", "image of…") go straight to Gemini with no Claude tokens, and so do `IMAGE_UPDATE_TRIGGERS` ("make it…") right after an image. **Fallback:** a `generate_image` client tool lets Claude hand off image requests the patterns miss. **One AI for everything (2026-11-05):** the AI chat also answers "how do I…" questions about the bot and runs commands for the asker. `!butler` (alias `guide`) is the same as `!ai`: the channel's shared conversation. @mentions outside AI threads and replies to the bot's other messages go there too. The old separate Haiku butler, with its own per-user sessions and `[ai]` hand-off, is gone, and `!claude butlerhandoff` was removed. Admins toggle @mentions with `!claude guidementions` and command-running with `!claude guideactions`. The quick model (`guide_model`, `!claude quickmodel`, aliases `guidemodel`/`butlermodel`) now only serves typo suggestions and other cogs' `complete(fast=True)`. There are deliberately no `howto`/`howdoi` aliases. `!butler` takes free text, so it must never get subcommands (a question starting with that word would run it). |
| `gemini` | `GeminiChat` | `9283748291` | **Image generation only** since 2026-11-02 (the old chat version was in `backups/gemini-2026-11-02/`, deleted 2026-11-04; recover it from git history if needed). `!draw <prompt>` and `!draw edit <changes>`, `!gemini setkey/list/settings/model/channelmodel`. Exposes `generate_image(prompt, session_key, reply_target, *, channel, user, new, quiet=False)` (`quiet` logs failures instead of posting them), which the Claude cog and ButlerFun call. It posts **just the image**, with no caption, so prompts aren't echoed and guess-the-game answers don't leak. **Keep that signature stable.** The API key is in Config global `api_key`. |

Quirks to know:
- **typing_extensions:** both AI cogs' `__init__.py` swap in a newer `typing_extensions` before importing their SDK, because pydantic needs `typing_extensions.Sentinel` and the venv's copy (4.13.2) lacks it. Red appends `Downloader/lib` to the *end* of `sys.path`, so the old venv copy wins otherwise. Gemini vendors a copy in `gemini/lib/`; Claude loads `Downloader/lib/typing_extensions.py` directly.
- **Claude cog design:**
  - Conversation history is stored as plain user/assistant **text** turns with no thinking blocks, so trimming old turns is safe under Anthropic's preserved-thinking rules.
  - **Persona:** the server's `persona` is used first, then its saved `default_persona` (`!claude defaultpersona <text|current|clear>`; up to `MAX_PERSONA_CHARS` = 3,000 characters, or attach a `.txt` file since Discord messages stop at 2,000), then the built-in `DEFAULT_PERSONA` (see `_persona()`). `!claude persona reset` clears `persona`, so the saved default takes over.
  - **Model choice:** a channel's model (`!claude channelmodel`, mods) must be in `allowed_models`; disallowing a model leaves channels that already picked it alone. Fable isn't in `MODELS`.
  - In every user turn, the speaker's display name comes first (`Name: message`).
  - **Attached images** go through `prepare_image`. The real format comes from the file's bytes (`sniff_image_type`), because Discord's `content_type` can be wrong, e.g. a PNG labeled `image/webp`, which the API rejects with a 400. Images over `MAX_IMAGE_BYTES` (3.75 MB raw, about 5 MB as base64) or longer than 1568 px are re-encoded with Pillow as JPEG at 1568 px. Uploads up to 25 MB are downloaded.
  - Mentions are passed through raw, with a note: `_mention_note` adds `(Who's who: <@id> is Name (speaking); …)` to every turn. It lists the speaker, the author of the replied-to message, and the users, roles and channels mentioned in either message. History keeps these notes, so Claude learns everyone's ID as the conversation goes. `MENTION_RULE` tells Claude to `<@id>`-mention people it talks about, but not the person it's replying to. Replies use `NO_MENTIONS`, so the name is highlighted but nobody is pinged. Image prompts for Gemini and re-seeded thread history use plain names instead (`_readable` / `clean_content`).
  - Sessions live in RAM, keyed `CHANNEL_<id>` or `THREAD_<id>`. They reset on reload or after `idle_minutes`.
  - After a restart, AI threads re-seed their context from recent thread history. The reply-to-continue index (`_answers`) is in RAM and isn't rebuilt, so replies to answers from before a restart are ignored.
  - Requests use the beta Messages API with `fallbacks: "default"` (refusal fallback), top-level `cache_control`, and the `web_search_20260209` tool when enabled.
  - **Knowing the bot:** `_catalog_sections` builds a fresh, sorted reference of every command, by cog: each command's usage, aliases, who can run it (from `requires`, inheriting from parent group or cog), and its help capped at 600 characters, with `[p]` and `[botname]` filled in. It skips hidden commands, disabled commands and cogs disabled in the guild. Bot-owner-only commands are included only for the bot owner.
    - The system prompt (`_bot_prompt_lines`) carries a short index (`_command_index`: each cog's first sentence plus its commands and subcommand names, about 1–2K tokens), the answer rules, the action rules and the handbook links. The date line comes last so the rest stays cached.
    - The `bot_commands` tool (strict; `sections` is an enum of this server's cog names, plus a `search` string) returns the asker's name and permission level, the requested sections in full, and up to 15 keyword matches from other sections (`_commands_result`, capped at 40,000 characters). The prompt requires a lookup in the same turn before naming or running any command.
    - The system prompt is sent as a block with its own `cache_control` breakpoint, so new conversations read it from cache (without it, every new or idle-reset conversation re-wrote ~8K tokens; measured 2026-11-05: about 2.6¢ a turn before, under 1¢ after).
    - A turn that used any lookup (`bot_commands`, `games_library`, `stats_report`…) or `run_commands` is `Turn.about_bot`: its reply is sent with `suppress_embeds=True`, and it doesn't count toward the daily limit. Over the limit the call still happens, but only `about_bot` answers are posted; anything else gets the limit line.
    - `_call_claude` returns a `Turn` (text, sources, stop_reason, images, action, about_bot).
    - **Server data rules** (2026-11-05): never state server data (owners, libraries, sessions, stats) unless a lookup or command returned it in the same turn, even on follow-ups, since history keeps only text. When one command shows exactly what was asked (`games whoowns`, `games mygames`, `games wanted`, `stats top`…), run it so the real card is posted; when it needs reasoning (what a group can play), use the lookups and answer from their results. A live run of follow-up questions passed (scratchpad `eval_unified.py` cases 23–30).
  - **Replies to the bot's other messages:** this covers anything not in `_answers`, such as GameManager announcements or AI answers from before a restart. When `guide_mentions` is on they go to the channel's conversation with `may_stay_silent`. The replied-to message is quoted (`ui.message_text`, which reads card text too), and the user turn itself tells Claude to answer `[silent]` (`GUIDE_SILENT`) if the reply is meant for other people. Then nothing is posted, no typing indicator is shown, and nothing is kept in history. Errors and refusals stay silent there too.
  - **Actions:** with `guide_actions` on, Claude gets a strict `run_commands` tool (`message`, `commands[]`). As with images, no `tool_result` is sent back; history gets a text note such as `[Ran: …]`. Waiting for a confirmation happens outside the session lock.
    - `_plan_actions` resolves each command with `bot.get_command` (longest prefix).
    - It refuses unknown and hidden commands, the butler/AI commands themselves (`ACTION_BLOCKED_COMMANDS`), and bot-owner-only commands.
    - It checks each command with Red's `can_run(ctx, check_all_parents=True)`, using a copy of the asker's message.
    - `_run_actions` invokes each command in order as the asker (`bot.invoke`), waiting at most 20 s per step.
    - Any command with a requirement label (mod/admin/permission/custom) needs the asker to press **Run** first (`ActionConfirmView`).
  - **Extension hooks for other cogs:**
    - A check predicate with a `requirement` attribute (e.g. GameManager's `game_admin()`, `"game admin"`) shows up as "(game admin only)" in the catalog and triggers confirmation.
    - A cog method `async guide_member_roles(member) -> List[str]` adds roles to the asker's permission label.
    - **Read-only lookups:** a cog with `guide_tools() -> List[tool dict]` and `async guide_call_tool(name, args, asker) -> str` offers lookup tools.
      - `_call_claude` runs up to 3 lookup rounds per answer, `bot_commands` included: tool_use → tool_result → final answer. The tool blocks stay within that turn; history stores only the final text. Text written before a lookup is dropped, the same way as for web searches.
      - A `run_commands` or `generate_image` call ends the loop.
      - GameManager offers `games_library`, `games_game` and `games_activity`, and ActivityStats offers `stats_report`. Prefix new tool names with the cog's name to avoid clashes.
    - **Unmet questions:** when no command fits, Claude ends its answer with `[no-command]` (`GUIDE_NO_COMMAND`). `_record_unmet` strips it and passes the question to ActivityStats' `record_unmet(guild, user, question)` if that cog is loaded.
    - **Cog events:** GameManager's `end_session` dispatches `gm_session_ended(guild, session)`; ActivityStats listens to record attendance.
  - When Claude calls `generate_image` (strict schema: `prompt`, `edit`), the cog runs it through Gemini and **does not send a tool_result back**. This saves a second API call. History records a text note such as `[Generated an image: "…"]` instead of tool blocks, so it stays text-only. Pricing for the usage estimates is in the `MODELS` table in `claude.py`; update it if prices change.
- **Command name conflicts:** the old chat Gemini and the Claude cog both define `ai`/`myai`/`aithread`. Only the image-only Gemini can be loaded alongside Claude.
- **ButtonGreeter buttons** are persistent `DynamicItem`s (since 2026-11-04), with the member's ID in each custom ID so "not for you" survives restarts: `bg:role:<role_id>:<member_id>`, `bg:custom:<member_id>`, `bg:none:<member_id>`, `bg:rules:yes|no:<member_id>`. Server settings are read at click time. Welcome messages posted before that change stay dead.
  - Only the welcome message pings, and only the newcomer.
  - `tagged_nick` is the one nickname rule: it replaces any leading `[TAG]`.
  - `report()` sends a short ⚠️ line to the admin channel; tracebacks only go to the log.
  - Without a rules role, the rules step is skipped and admins get a note.
  - Saying No keeps the rules prompt up so the member can change their mind.
- **GameManager internals:**
  - **Persistent buttons:** session, vote, request and install buttons are discord.py `DynamicItem`s (custom IDs `gm:s:<action>:<sid>`, `gm:v:<vid>:<gid>`, `gm:r:<action>:<rid>`, `gm:i:<rid>`), registered in `cog_load`. They keep working after restarts. Buttons posted by the pre-2026-11 version used static IDs and are dead.
  - **Vote timers:** they live in `self.vote_tasks`. `_resume_votes` reschedules them from each vote's `ends_at` on load.
  - **Background loops:**
    - `session_loop` (every minute) sends reminders and start pings, ends sessions 12 h after start or creation, and posts recurring sessions `RECURRING_POST_HOURS` (24) ahead.
    - `sale_loop` (every 6 h) refreshes wishlist prices and posts sale and free-game alerts.
  - **Posting sessions:** `create_session` only parses input; `post_session` posts the message and creates the Discord event.
  - **Buried cards (2026-11-05):**
    - **Moving a card:** `move_session_card(guild, session, ping_ids=)` reposts the card at the bottom and deletes the old one. It also deletes the old ping lines and the in-card vote's `ping_id`. It updates the session's and in-card vote's `message_id`, and `_relink_event` fixes the event description's link. A per-session lock (`_move_locks`) stops a card moving twice at once. An embed session from before cards comes back as a card.
    - **Automatic moves:** `announce()` (the reminder, the start, and the vote via `start_vote`) moves the card instead of sending a ping line when `_buried()` finds at least `BURIED_AFTER` (10) messages below it. The moved card pings the players, since it names them.
    - **On request:** `games here` / `/games here` (`bring_here`) moves the latest session in the channel, at most once per `HERE_COOLDOWN` (60 s) per channel.
    - **Join and leave by command:** `games join` / `games leave` and the slash versions call `join_or_leave`. `pick_session` resolves the session: by title or ID, else the only one in the channel or the server. The slash commands' session autocomplete gives the ID. `set_membership` is the shared join/leave logic for these commands and the card's buttons.
    - **Shortcuts:** top-level `!session` (group) and `!sessions` are short for the `games` session commands. `!session` alone runs `bring_here`. Its subcommands are `new` (aliases `create`/`host`), `join`, `leave`, `here`, `vote` and `end`.
      - Starting needs `new`, because a title like "join the raid" would otherwise read as a subcommand.
      - The group's catch-all `words` argument (hidden with `usage=""`) means SpeakUp treats a stray word as an argument and stays quiet; the group answers with its own "add `new`" hint instead.
      - Handbook's `topic_for` maps both to the Game nights page.
  - **Event details (2026-11-05):**
    - **Stored data:** sessions and schedules keep `event` = `{description, minutes, voice_id, banner}`. Banners are files under `cog_data_path(self)/banners/<owner>.<ext>`, where owner is the session or schedule ID; a posted occurrence points at its schedule's file.
      - `store_details(owner, details)` writes any new `banner_data` bytes.
      - `drop_banner(name, owner)` deletes only the owner's own file (on `end_session` and `recurring stop`).
    - **Building the event:** `_event_fields` builds the description (the host's text, then how to join), the place (the session's voice channel, else `event_channel`, else external with the text channel), and `end_time`: `minutes`, or `EVENT_LENGTH_HOURS` when external.
      - `create_event` and `push_event` (which edits the event, or creates it if missing) use it.
    - **Setting details at start:**
      - `/games session` has description, banner (attachment), voice and length options.
      - Text commands use `details_from_message`: lines after the first are the description, an attached image is the banner, and a mentioned voice channel is taken out of the title. The AI chat's `run_commands` runs on a copy of the asker's message, so its attachments come along; the Claude cog's `one_line()` shows only a command's first line in its "Running:" note.
      - Bad banners are refused with `read_banner` (10 MB; PNG, JPG, GIF or WebP by magic bytes, `image_ext`).
    - **Edit event:** scheduled sessions' cards have it (`SessionButton` action `event`). It opens `EventDetailsModal` (discord.py 2.7 `Label`, `ChannelSelect`, `FileUpload` and `CheckboxGroup`), which has 5 fields: description, length, voice, banner, and options ("Remove the banner"; "Also use for future sessions" on repeating ones).
      - `apply_event_details` saves the form; "future" also writes the schedule's `event` and stores the banner under the schedule's ID.
    - **Banner on the card:** the card shows the event's own cover image full width above the title (`ui.card(banner=url)`), from `event["cover_url"]`.
      - That's Discord's CDN copy, so moving or redrawing the card never re-uploads it.
      - `create_event` sets it on the session it's given, `push_event` refreshes it after an edit, and `on_scheduled_event_update` picks up a banner changed in Discord.
      - Schedules never store `cover_url`, because each week's event has its own.
    - **Edits made in Discord:** `on_scheduled_event_update` copies a changed time (recomputing `reminded`), name and voice channel (compared with the effective default) to that one session. A cancelled event ends the session.
  - **Winner history (2026-11-05):** sessions keep `winners` (every vote's winner, in order, repeats included); `finish_vote` appends, seeding from `winner` for older sessions. The card's result block, and the ended card, add `Earlier: …` (`played_text()`, which counts a run of repeats as "(won twice)"). Later votes never leave out earlier winners: a vote to switch can keep the current game. Recurring schedules (guild `recurring`) use `post_session` too.
    - A schedule stores weekday, hour, minute, `interval` (7 or 14), the host's timezone name and `next_start`. `advance_occurrence` rebuilds the local time each time, so daylight saving changes don't shift it. Input starting with `every`/`weekly` goes to `create_recurring`.
  - **Discord events:** `create_event` makes an external event (the location is the text channel, ending after `EVENT_LENGTH_HOURS`), or a voice event if `event_channel` is set. It needs Manage Events.
    - `update_event` starts it at the start ping and ends or cancels it in `end_session`.
    - `on_scheduled_event_user_add/remove` treat Interested as Join or Leave.
  - **Wishlist:** guild `wishlist` is keyed by Steam app ID: `{appid, name, users, price, checked_at, alerted}`.
    - `alerted` is the last discount seen, so an alert fires only when the discount rises.
    - Owners are worked out at alert time from library games that have the same `steam_appid`.
    - Prices come from Steam's `appdetails` (`filters=price_overview`, batches of 50, US). Free Epic games come from the unofficial `freeGamesPromotions` feed.
  - **Profile setup:** `ProfileWizard` draws every screen as a new view and stops the old one. Pickers (`GamePickerView` with `on_cancel`) take over the message and hand back to the wizard. Modals use `TextModal`. `start_profile` is shared by `!games newprofile` and `/games newprofile`. The guide may run `games newprofile` even though it opens a menu.
  - **Writes:** all go through `async with config…() as x` (Red locks these) so simultaneous clicks don't lose updates.
  - **Name lookups:** they use `resolve_game`, which matches exactly first and accepts a partial match only if it's unique.
  - **One implementation, two front ends:** shared methods take a `Target` (a Context or an Interaction), so text and slash commands reuse the same code.
  - **Game-admin commands:** use the `game_admin()` check, which raises `UserFeedbackCheckFailure` so the user sees why.
  - **New game names:** they pass through `checked_names` before a request or add (`!games request`, `/games request`, `!games admin add`, and the Request/Add buttons).
    - `suggest_titles` tries, in order: a library near-match (difflib), Steam's exact-name store search (`steam_exact_title`, no key), then the Claude cog's public `find_game_title(name, member)`.
    - Fixes that only change capitalization or symbols apply silently. Real spelling changes need the person to confirm (`NameCheckView`).
    - Games and requests store `steam_appid` when one is known.
  - **`find_game_title`** (Claude cog) tries Haiku with `web_search_20260209`, then Haiku with `web_search_20250305`, then Sonnet (`TITLE_SEARCHERS`). It remembers the first option the API accepts, and it reports through a strict `report_title` client tool without sending a tool_result back.
- **Other public Claude cog helpers:**
  - `complete(member, channel, *, system, messages, fast=False, max_tokens, persona=True, count_toward_limit=True)` is used by ButlerFun. It returns `(text, None)` or `(None, a user-facing error)`. `fast` uses the quick model (`guide_model`) and otherwise the channel model. It puts the persona first, records usage, respects the daily limit, and turns on top-level caching. On models with `fallback` it uses the beta endpoint with `fallbacks: "default"`, like the AI chat.
    - A refusal returns exactly `ClaudeChat.REFUSAL` (`"❌ I can't help with that one."`), and callers compare `error == claude.REFUSAL`. An empty reply returns `NO_REPLY`, which isn't a refusal.
    - Other public helpers: `limit_reached(member) -> Optional[int]`, which ButlerFun uses to name whose limit stopped an adventure round, and `limit_text(limit)`, the single wording for the daily limit.
    - A missing API key shows "⚠️ AI chat isn't set up yet…", with the setup command shown to the bot owner only.
    - `ActionConfirmView` is an `ExpiringView` (`expired_note` "Expired. Nothing was run."); after running, its "Running…" note changes to "Done.".
    - Long replies use `ui.split_text`; `split_for_discord` is gone.
  - `summarize_link(url, member)` reads the page with Anthropic's **web fetch** server tool, so the bot never requests user-posted URLs itself (no SSRF into the Docker host's network). It follows the same fallback pattern (`LINK_READERS`: Haiku `web_fetch_20260209`, then `_20250910`, then Sonnet, with `max_content_tokens` 12000) and keeps only the text after the last tool block.
  - `suggest_command(message, typed)` sends the quick model the whole command reference (`_command_catalog`) as a cached system prompt, with no tools. It accepts the reply only if it starts with the prefix and names a real, non-hidden command.
- `censord` reads guild and channel Config on every message.
- `data/cogs/ButtonGreeter/` holds an **older, stale copy** (far behind since the 2026-11-04 rewrite) of `buttongreeter.py`, `__init__.py` and `info.json` next to its `settings.json`. That copy isn't loaded; the live code is in `CogManager/cogs/buttongreeter/`. Don't edit the stale copy by mistake.
- The `info.json` files have placeholder authors (`"YourName"`, `"Claude"`); the real author is Quillshot.

## Handbook site (`docs/`)

- **Publishing:** the user handbook is a Jekyll site published by GitHub Pages from `main` → `/docs`, at https://bradqui.github.io/ButlerBot/ (`baseurl: /ButlerBot`, theme `just-the-docs` via `remote_theme`). Pages need the repo to be public.
- **Pages:** task-based and written for members, with mod/admin notes in `{: .staff }` callouts. Each page's `permalink` must match the Handbook cog's `TOPICS`.
- **Links:** internal links use `{{ '/path/' | relative_url }}`.
- **Reference:** `docs/reference/` is generated; don't hand-edit it.
  - **Our cogs' pages:** `python tools/build_reference.py` regenerates them offline. It loads every cog whitelisted in `.gitignore` with a stand-in for Red and renders each page with the Handbook cog's own `build_reference`, so the output matches the live export. It also updates their rows in `index.md`, and `--check` only reports what's stale. **Run it whenever a change adds, removes or rewords a command of ours, and commit the pages with the change.**
    - Setup, once: `python -m pip install --target tools/.pylibs -r tools/requirements.txt`. The libs folder is gitignored.
    - It can't see server Permissions rules. If one of our cogs or commands is ever denied by default, add it to `DENIED` in the script.
  - **Everything else** (Red's built-in cogs, third-party cogs, and `custom-commands.md`) still comes from `!handbook export` on the live bot. That's only needed after a Red or `!cog update`, or after custom commands or aliases change.
- **When features change, update the matching page.**

## Third-party cogs (do NOT edit in place)

Installed via Downloader. Any `!cog update` overwrites their files in `CogManager/cogs/`, and the matching sources in `RepoManager/repos/` are git clones:

`antispam` (flare-cogs), `roletools` (Trusty-cogs), `autoroler` (Dav-cogs), `autoroom` (pcxcogs), `system` (vex-cogs), `easytranslate` (crab-cogs), `chatchart` (aikaterna-cogs), `clearchannel` + `consolelogs` (aaa3a-cogs, which need the `AAA3A_utils` lib), `customhelp` (npc-cogs).

**Known third-party quirk:** `system` (vex-cogs) puts `has_permissions(embed_links=True)` above `is_owner()`. Red's `get_decorator` overwrites `privilege_level`, so the owner restriction is lost and anyone with Embed Links can run `!system …`. The fix, without editing the cog, is `!permissions setdefaultglobalrule deny System` (the owner always bypasses rules).

To change one of these, fork it into a new, differently named package under `CogManager/cogs/` rather than patching the Downloader-managed copy. The repo clones are a good reference for idiomatic Red cog code.

Loaded packages, from `core/settings.json`: admin, alias, cleanup, customcom, downloader, filter, general, modlog, mutes, permissions, trivia, warnings, mod (core), plus antispam, autoroom, system, easytranslate, censord, gamemanager, buttongreeter, chatchart, clearchannel, consolelogs, customhelp, gemini. `roletools` and `autoroler` are installed but **not loaded**.

## Coding conventions for cogs here

- Use Red's `Config` for all persistence: `Config.get_conf(self, identifier=<int>, force_registration=True)`, then `register_guild/channel/user/global`, and `async with self.config.guild(g).thing() as x:` for mutations. **Never change an existing cog's identifier**, because that orphans all of its saved data. For non-Config files, use `redbot.core.data_manager.cog_data_path(self)` (as Censord does).
- Permission checks use `redbot.core.checks` / `commands` decorators (`admin_or_permissions`, `mod_or_permissions`, `is_owner`, `guild_only`), plus each cog's own configurable admin/mod role.
- UI is built with `discord.ui` views, modals and (from the 2026-11 overhaul) Components V2 layouts; interaction errors are reported ephemerally. Follow **Message style** below.
- Match the existing code style: section-divider comments.
- Prefer `logging.getLogger("red.<cogname>")` over `print`. Output lands in `core/logs/`.
- Clean up background tasks in `cog_unload`.
- When adding a dependency, list it in the cog's `info.json` `requirements`. Packages land in `data/cogs/Downloader/lib/`.

## Message style (all of our cogs)

The approved design is the proposal at https://claude.ai/artifact/6SZSwTsiqe2gxeyKE1Dorq (2026-11-04). The rollout is in four phases:
1. The shared module and the audit's bug fixes.
2. Cards: sessions, votes, requests, Steam, the time answer, help, settings.
3. Boards: paged lists, stats reports.
4. Less noise: a game night as one card, offers that clean up, personal numbers private.

**Shared module:** `CogManager/cogs/_shared/butlerui.py`. It isn't a cog: the folder has no `__init__.py`, so Red doesn't list it. Red doesn't put the cogs folder on `sys.path`, so every cog loads it with the `_load_butlerui()` snippet from that file's docstring, which re-reads the file when it changes. It provides:
- the colors and status symbols;
- `line()`, `hint()`, `plural()`, `truncate()` and `split_text()`;
- `ExpiringView`, a one-person menu that greys out and says "Expired.";
- `edit_quietly()` and `respond()`, which are private and ping-free by default.

Use it instead of local copies.

**Colors.** Six, each with one meaning:
- `BRAND` is Discord blurple: info, lists, settings, help.
- `SUCCESS`: done, joined, live.
- `HIGHLIGHT`: winners, results, sales.
- `ATTENTION`: needs someone to act.
- `DANGER`: denied, removed, failed.
- `MUTED`: ended, cancelled, expired.

Staff-only cards keep these colors and add a "Staff only" hint, rather than using an admin color.

**Status symbols.** Put one at the start of a line, with these meanings only:
- ✅ done
- ❌ couldn't do it (say what went wrong and what to do)
- ⚠️ heads-up, or something needs setting up
- ⏳ working, busy or a limit was reached
- 🔒 not allowed for you
- ❓ didn't understand, not found, or did you mean

Rules for using them:
- Don't use 🛑 ⌛ 😶 🚫 💳 🔑 📡, "Error:" or Title Case labels as status markers. Game moments such as 🏆, ⌛ "Time's up" and 🏁 are fine.
- Picker checkboxes are ☑️/⬜.
- Each feature keeps one topic emoji for titles: 🎮 games, 🗳️ votes, 🤖 AI chat, 🎨 images, 🤵 butler, 📊 stats, 🗣️ SpeakUp, 🗺️ adventures, 🧠 trivia, 🛡️ filters, 👋 welcome, 📖 help.
- At most one emoji per line.

**Message sizes:**
- **Line:** one sentence, with an optional `-#` hint under it. It's private when there's an interaction. Text-command errors stay in the channel (the user's choice, so don't auto-delete them).
- **Card:** a V2 container with an accent color, a short title, the details, its buttons inside, and a `-#` footer hint.
- **Board:** a card that pages, 8 rows with ◀ ▶, and a **Jump to** menu past 5 pages.

**Readable rows and blocks** (Phase 5, 2026-11-05; approved design: https://claude.ai/artifact/KkhZn2GtYB15WMQoueEKeN). Discord can't put small or colored text in the middle of a line (`-#` only works on a whole line) and has no columns, so:
- **One main line, details underneath.** The thing a row or block is about (a game, a person, a command, a fact) is the main line, usually **bold**. Its counts, explanations and secondary names go on a `-#` line under it, never after a `·` on the same line. Build board rows with `ui.row(main, detail)` and card blocks with `ui.two_line(main, detail)`.
- **Every list is two-line rows, short lists included.** A name-only row is just the bold main line. Each row is its own text block, so Discord adds space between rows.
- **Markers go at the end of the main line** (`**Barony** 💾`), so they line up and never sit between a name and its details.
- **Cards are short blocks**, each a bold main line plus a small detail line (for example a session card: when, who, the vote). Instructions people only need once go into the private reply they get when they press a button, not into the card.
- **At most one emoji per card body line**, and only where it means something; the title keeps the topic emoji. Fact lists (stats reports) drop per-line emoji.
- **Footers say one thing:** the page count plus at most one hint. Lists of commands belong in help, not footers.
- **Settings cards are the exception:** `settings_text` keeps `**Name** · value` rows, since those are key-value pairs read as a table.

AI answers, adventure narration and butler replies stay plain text, split with `split_text()` (never by slicing).

**Building cards** (`butlerui`):
- **`card(*parts, title, color, footer, thumbnail, banner)`** builds a `discord.ui.Container` (`banner`: an image URL shown full width above the title). Parts can be:
  - strings, which become text blocks;
  - `SEPARATOR`;
  - lists of buttons or selects, which become action rows (five buttons to a row, each select on its own row);
  - any `discord.ui` item.

  The title is rendered as a `### ` heading. The footer becomes a `-#` hint.
- **`CardView(card(...))`** is a `LayoutView`. Subclasses override `build()` and call `redraw()`.
- **`ExpiringCard(owner_id, …)`** is the card version of `ExpiringView`. It has an owner check, and on timeout it disables its items and adds a note line. Link buttons stay live.
- **`settings_text([(name, value)])`** writes `**Name** · value` rows, with On/Off for booleans.
- **`send_card(target, view, ephemeral=…, reply_to=…)`** sends to a Context, channel, user or interaction.
- **`is_card(message)`** tells you whether a message is a card.
- **`Board(title, rows, *, color, header, footer, per_page=8, media, empty, owner_id=None, timeout=900, extra)`** is a paged card (Phase 3, two-line rows since Phase 5). Send it with `await board.send(target, ephemeral=…)`.
  - Rows are `ui.row(main, detail=None)` tuples (or plain strings, which are a main line with no details). `ui.row_text(r)` gives a row's markdown; `ui.plain(text)` strips markdown and mentions for labels.
  - Each row on a page is its own `TextDisplay`. More than `JUMP_AFTER` (5) pages adds a **Jump to** select above the rows (`board:<id>:jump`): one option per page, labeled "Page N" with "first – last" row names, grouped into ranges past 25 pages.
  - Anyone can page it with ◀ ▶. Paging redraws the same message, and the custom IDs are stable per board.
  - A single page has no buttons and no timeout.
  - Pages also break by size, at about 3,400 characters of rows.
  - On timeout the buttons grey out, with "Run the command again to page through it."
- **`image(url, description)`** puts a picture in a card. For an uploaded file, use `"attachment://name.png"` and send the file with the card. A card hides attachments it doesn't reference.

Rules for card messages:
- **They can't have content or embeds**, and Discord never lets a message switch back. Persistent features switch for new messages only, and their handlers must check `is_card(interaction.message)` and edit older embed messages the old way.
- **Mentions in card text DO ping**, unlike embeds. `send_card` therefore defaults to `NO_PINGS`; pass `allowed_mentions` explicitly for a deliberate ping.
- **Size limits:** 40 components per message, and roughly 4,000 characters of text.
- **Persistent buttons:** `DynamicItem` buttons work inside a card's action rows.
- **Settings cards** are titled "<topic emoji> <feature> settings", in `BRAND`. The body is `settings_text` rows, with optional bold group headings. A separator comes next, then a footer hint naming the change commands, plus "Staff only" when only staff can see the card.
- **Tests:** the harness's `card_text(msg)`, `card_buttons(msg)` and `card_color(msg)` read card messages, and fake messages get `flags.components_v2` when they carry one.

**Buttons:**
- Labels are a verb of three words or fewer. Put emoji on every button in a row or on none; icon-only buttons are fine for 🗑️ and ◀ ▶.
- Blurple (primary) is for the one main action. Grey is for everything else, Cancel and Keep included. Red is only for the confirm step of something destructive, and green isn't used for ordinary buttons.
- More than five choices means a select menu.
- Menus that expire disable their items and add "Expired." (`ExpiringView`).

**Words:**
- Sentence case. Display names, never usernames.
- Feature names people know ("AI chat", not "ClaudeChat").
- Discord timestamps for times. Timestamps don't render in embed titles, so only use them in text.
- Command hints always use the real prefix; never show a literal `[p]` to users.
- Use `plural()`, never "(s)".
- Never post raw API or exception text: log it and show a short sentence instead.

**Pings:** only on purpose, for reminders, sessions, LFG, sale alerts, and the welcome greeting. Everything else uses `ui.NO_PINGS`, or `mention_author=False` on replies. **Gotcha:** `discord.AllowedMentions(users=[m])` leaves `everyone` and `roles` on, so pass `everyone=False, roles=False` too.

**Phase 1 per-cog notes (2026-11-04):**
- **GameManager:**
  - Each menu sets its own `expired_note` (for example "Expired. Nothing was saved."). Menus are `OwnerOnlyCard` since Phase 2.
  - Installed games are marked 💾 (`INSTALLED`). `prefix(guild)` feeds `cmd()`.
  - Host and admin refusals, including `game_admin()`, are 🔒. ⚠️ means "already that way", and ➖ only means removed.
  - Session buttons: Join is primary and the rest are grey. Vote options are grey, and Approve is primary.
- **SpeakUp:**
  - 📄 goes on every summarizable link, with no cooldown (the user's choice, 2026-11-05). Only 🕘 has a per-channel cooldown.
  - `summary_text()` shortens summaries to fit one message. A failed post leaves the offer clickable again.
  - `ConfirmRemoveView` is an `ExpiringView`. Run it expires after 5 minutes, but its Remove button keeps working.
  - The Steam card is `HIGHLIGHT` when on sale and `BRAND` otherwise, with grey 📚/⭐ buttons.
- **ActivityStats:**
  - Every report uses `BRAND`. Admin reports add a "Staff only" footer (`STAFF_HINT`).
  - The digest title uses plain dates (`short_date`), since embed titles can't show timestamps.
  - `daily_chart(colors=…)`: joins are green and leaves red.
  - People who left the server are counted, not mentioned (`_names_or_departed`).
- **Gemini:** the public `image_models()` lists the image models. `!gemini channelmodel` checks names against it: aliases always pass, and a ⚠️ hint appears when the list can't be fetched.
- **Handbook:**
  - Cards use friendly cog names (`COG_NAMES`, `friendly_name()`), and `!help <friendly name>` finds the cog.
  - Every card uses 📖; `fit()` shortens long text. Boards use `HELP_FOOTER` ("`!help <command>` for details"); single-command cards point at related commands instead (Phase 5).
  - Topic emoji: filters 🛡️, moderation 🔨.
- **Censord:**
  - `addword`/`delword` delete the command when they can, never repeat the word, and report honestly; `_update_csv` returns whether the list changed.
  - `threshold` values must be at least 1.
  - The "watch your language" warning mentions the person without pinging them.

**Phase 2 per-cog notes (cards, 2026-11-05):**
- **GameManager:**
  - **Card messages.** Sessions, votes, requests, install requests, sale alerts, free Epic games, the settings card ("🎮 Game night settings") and every menu are cards. New records store `"card": True`, and `_edit_record()` edits cards as cards and older records with the old embed and View.
    - The legacy helpers `session_embed`, `vote_embed`, `session_view`, `vote_view` and `request_view` remain only for old messages.
    - `_drop_buttons()` strips buttons from old embeds only.
    - Votes store `labels` so redraws can rebuild their buttons.
  - **Builders.** Card builders are `session_card`, `vote_card` and `request_card`. `pings(ids)` makes a users-only `AllowedMentions` (up to 100 people) for the vote, sale and install cards, which still ping the same people as before.
  - **Menus.** Menus build on `OwnerOnlyCard(ui.ExpiringCard)`, which replaced `OwnerOnlyView`.
    - Every final state goes through `final_card()`, because a card can't turn back into text.
    - `ConfirmView(user_id, text, label, title=)` and `NameCheckView(user_id, plural, text)` have new signatures, and the picker's `embed()` is now `text()`.
  - **Results.** Library and request results are plain lines: `change_library_text()` and `request_games_text()`. The embed versions `change_library()` and `request_games()` remain as compatibility wrappers.
  - **Still as before.** `send_list` lists stay embeds until Phase 3. The plain-text announcements and pings stay until Phase 4.
- **SpeakUp:**
  - The Steam card comes from `steam_card(guild, appid, details, remove_uid)`. Clicks redraw card messages only (`_refresh_steam_card`), which reads the Remove owner back from `message.components`. Details are cached in `_steam_info`.
  - SpeakUp prefers GameManager's `*_text` helpers (`result_text()` handles every shape).
  - Inside cards, `RemoveButton(uid, compact=True)` is icon-only.
  - The time answer, `!speakup` settings and `!reminders` are cards. Summaries and the mistake suggestion stay text.
- **ActivityStats:** the `!stats admin` menu and settings are 📊 cards marked "Staff only". Reports and the digest stay embeds until Phase 3.
- **ButtonGreeter:** `welcome_card(member, roles)` and `rules_card(member, rules)`. The welcome card is the only card sent with a ping (just the newcomer).
- **Censord:** the `censor config` card lists channels by name and shows per-channel overrides.
- **Handbook:** every help reply is a card from `_send_card`, with link buttons inside.
  - (Superseded in Phase 3 and 5: help lists are boards of two-line rows.)
  - If Discord rejects a card, the ❌ fallback line is sent instead.
  - The export format is unchanged.
- **Claude:** `!claude settings`, `models` and `usage` are cards. Usage for another member, and the server totals, carry "Staff only". The persona is shown in full only by `!claude persona`, as text.
- **Gemini:** `!gemini settings` is the "🎨 Image settings" card. `!gemini list` sends one card per 3,500 characters.
- **Tests:** the scratchpad harness checks every card sent or edited against Discord's limits. Problems print as `LAYOUT PROBLEMS` at the end of a run.

**Phase 3 notes (boards, 2026-11-05).** These replace the Phase 2 notes that said lists, reports and the digest were still embeds.
- **GameManager:**
  - `send_list(target, items, title, footer, ephemeral, *, header, empty)` posts a `ui.Board`. An empty list sends a ❓ line unless `empty=` is passed.
  - Private boards sent through an interaction time out at `LIST_PRIVATE_TIMEOUT` (840 s), before the 15-minute token dies; others at `LIST_TIMEOUT` (900 s).
  - `library_rows()` counts current members only. Since Phase 5 its rows are `ui.row("**Name** 💾", "4 own · 3 installed")`.
  - Every list title uses 🎮, and vote tallies use 🗳️. `top` and `wanted` have no cap; paging handles the length.
- **ActivityStats:**
  - **Rendering:** reports and the digest are boards built by `_report_card(report, footer) -> (Board, file)`. The chart is `attachment://stats.png` with alt text from `Report.alt`.
  - **Paging:** `Report.rows_from` and `start_list()` mark where the paged list starts, and the lines before it repeat on every page. `split_row` (`ROW_ROOM` 450) breaks long rows only at ", ".
  - **Charts:** transparent background, `#80848E` text and 12 pt ticks, 960 px wide.
    - Line colors come from `CHART_COLORS`/`CHART_STYLES`: blurple, then deeper green `#3BA55C` and gold `#D4A20A`, then fuchsia, dashed or dotted after the first. The bright palette green and gold vanish on white.
    - A chart shows at most 4 lines (`MAX_CHART_SERIES`).
    - Joins are `CHART_GOOD` and leaves `CHART_BAD`.
    - The heatmap is a blurple opacity ramp, which stays monotonic on both themes.
  - **Digest:** its channel needs Send Messages and Attach Files.
- **ButlerFun:**
  - `maketrivia show` is a 🧠 board. Rows come from `trivia_row()`: the question is cut at 420 characters and the answer at 150, so a spoiler is never split. The `.txt` file is gone.
  - The no-name version is the "🧠 Trivia lists" board.
  - `guessgame top` is a HIGHLIGHT board of every winner.
- **SpeakUp:** `!reminders` is a board.
- **Handbook:**
  - Help for groups and cogs is a board from `_send_board()`. The header repeats on each page, link buttons go in `extra`, and the cog card's divider goes in `media`.
  - Plain command cards and the home card are single cards. (`rows_per_page()` was removed in Phase 5; the Board's size paging is enough.)
- **Gemini:** `!gemini list` is one board.
- **Claude:** `usage` and `models` stay cards, since neither can pass one page.

**Phase 4 notes (less noise, 2026-11-05):**
- **GameManager game nights are one card.**
  - **Votes run inside the card.** A vote on a card session runs inside the session card. The vote record has `in_card: True`, points at the session message, and stores `ping_id`.
    - While voting, the card turns `ATTENTION`, shows "Voting ends <t:R>" and puts the `gm:v:` buttons inside.
    - Afterwards it's `SUCCESS` again and shows the session's `vote_result` (🏆 winner and medals).
    - `session_card(session, ended, vote)`, `vote_status()` and `session_card_now()` draw it.
    - `vote_card` is only for older records and embed sessions.
    - There's no "30 seconds left" ping any more.
  - **Pings are short lines.** `ping_line()` and `_ping()` build them, linking to the card with `message_link()` and pinging the same people as before through `pings()`. They're tracked in the session's `pings` and the vote's `ping_id`, and `_delete_messages()` deletes them when the vote or session ends. A game night leaves only its card behind.
  - **Other cleanups:**
    - The host-timezone note is a hint in the card (session `tz_note`; `post_session(..., tz_note=)`).
    - A request result is a one-line ping to the requester. `request_card(..., note=)` carries the owned/installed note.
    - Sale alerts name each person once.
- **SpeakUp offers clean up.** `_take_back()` removes the bot's own 🕘/📄 once the answer is posted. `sweep_offers()` runs in `reminder_loop` every `SWEEP_SECONDS` (600) and takes back offers unused after `TRACK_SECONDS`. Tracked entries store `channel` and `guild`. Reactions from before a restart aren't tracked and stay.
- **Personal numbers go to DMs** with a ✅ tick on the command: `!stats me` (yourself), `!claude usage` (yourself) and `!maketrivia show <list>`.
  - Each uses `ui.send_private(ctx, build)`, where `build(in_dm)` returns a view or `(view, file)`. If DMs are closed, the reply goes to the channel with `ui.DM_FALLBACK` in its footer.
  - Staff views of other people stay where they were asked, marked "Staff only". `!stats me @member` now shows that too.
- **Tests:**
  - `enable_dms()` in the harness gives fake members a `send` (`member.dms`, `member.dms_closed`).
  - `FakeMessage.delete()` records into `channel.deleted`.

**Phase 5 notes (readable rows, 2026-11-05).** The rules are under "Readable rows and blocks" above. Every list and card was converted and reviewed against the whole style guide.
- **butlerui:**
  - `row()`, `row_text()` (main line and details capped separately at `ROW_PART_LIMIT`, 600 characters), `two_line()` and `plain()` (strips markdown, links, mentions and emoji, but keeps escaped characters).
  - `Board` defaults to 8 rows, each its own text block, with a Jump to menu past 5 pages.
- **GameManager:**
  - **Lists:** every `send_list` takes `ui.row`s. The module helpers are `details(*parts)` (" · " joined, capitalized), `name_list()`, `repeat_short()` and `tz_note_parts()`.
  - **Session card:** `session_card(..., guild=)` draws short blocks: when, who, and the vote. `vote_status(vote, guild)` returns one block.
  - **Vote buttons:** `vote_buttons(vote)` labels buttons with running tallies ("Deep Rock Galactic · 2"; none at zero). New votes store plain names in `labels`.
  - **Voting guidance:** it's in the private reply after a vote, not in the card. Older vote cards keep their lines via `vote_lines()`.
  - **Request card:** always titled "🎮 Game request: X", with an Approved or Denied block.
  - **Menus:** the profile summary uses `settings_text`. Wizard and name-check buttons have short verb labels ("Pick games", "Type names", "Keep my spelling", "Add to library", "Skip it").
- **ActivityStats:**
  - **Report contents:** `Report.lines` hold `ui.row` tuples or strings, and every report title uses 📊 with no per-line emoji.
  - **Rendering:** `ReportBoard` draws each summary block as its own text block. `report_layout` returns `(blocks, rows)`, and `_plain` writes `main — detail`.
  - **Helpers:** `trend()`, `ranked_main()` (`**1. Alex** 🥇`, medal at the end) and `leader_row()`.
  - **Smaller changes:** the overview footer is "More with `!help stats`". `ChannelPicker` uses a select menu for 6 or more channels. `!stats admin digest` with no subcommand shows a "📊 Digest settings" card.
- **Handbook:**
  - Help rows are the usage in code as the main line, with the first sentence of the help as the detail (`first_sentence()`, `_command_row()`). Who can run it is added only when that isn't everyone.
  - Each home card topic is its own block.
- **SpeakUp:**
  - The reminders board rows are the bold text, with the time, place and ID underneath.
  - The Steam card puts its price and owners on small lines.
  - The settings footer is a single line.
- **ButlerFun:**
  - Trivia rows are the question, with the `||answer||` underneath.
  - `guessgame top` rows are `**1. Mira** 🥇` with the wins underneath.
  - The catch-up header uses two lines.
  - Status symbols are fixed (❓ for not found, ⏳ for the adventure limit).
- **Claude:**
  - `!claude models` is a board of two-line rows.
  - `!claude usage` (server) lists every member who has usage, paged, under a header of totals.
  - `limit_text()` adds a `-#` "resets <t:R>" line.
  - Error replies are one line plus a hint.
- **Gemini:** `!gemini list` rows are the model, with its shortcut and where it's used underneath. Footers are a single hint.
- **Censord:**
  - Each channel override in the config card is its own block, capped at `MAX_OVERRIDES_SHOWN` (10).
  - The kick and ban reason is "Word filter: repeated offensive language".
- **ButtonGreeter:** the welcome and rules cards use `two_line()`, and replies are one line plus a hint (`TOLD`).
- **Settings card footers** may say "`!help <group>` shows how to change these" in place of listing commands, plus "Staff only".

## Secrets (never print, log, or copy out)

- `data/core/settings.json` → `GLOBAL.token` (Discord bot token) and `SHARED_API_TOKENS` (e.g. openweathermap)
- `data/cogs/GeminiChat/settings.json` → Gemini `api_key`
- The Anthropic key is in `core/settings.json` under `SHARED_API_TOKENS.anthropic`

When inspecting these files, redact secrets programmatically instead of catting the whole file.

## Editing config data

Don't hand-edit any `settings.json` while the bot is running: the JSON driver keeps data in memory and overwrites manual edits. Change settings through bot commands, or stop the container first. The Censord CSVs are the exception; edit them on disk, then run `!censor reload`.
