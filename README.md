# Red

Custom cogs and deployment setup for our [Red-DiscordBot](https://github.com/Cog-Creators/Red-DiscordBot) instance.

The repo mirrors the bot's data directory (`data/`, mounted at `/data` in the Docker container), but only our own code is tracked. Everything else in `data/` is runtime state that stays on the server: the bot token, API keys, per-server settings, logs, the Python venv, and the third-party cogs.

**Runtime:** Red 3.5.24 · discord.py 2.7.1 · Python 3.11 · Docker (`phasecorex/red-discordbot`) · JSON storage · prefix `!`

## Custom cogs

All of them live in [`data/cogs/CogManager/cogs/`](data/cogs/CogManager/cogs/).

| Cog | What it does | Main commands |
|---|---|---|
| [`claude`](data/cogs/CogManager/cogs/claude/) | AI chat with Anthropic's Claude (Sonnet 5.5 by default). It has shared channel conversations, private conversations, and AI threads. Replying to an answer continues the conversation. It reads images, PDFs, and text files, can search the web and cite sources, and tracks usage and cost, with optional daily limits. Image requests are handed to Gemini. It also includes a **bot guide** that uses Haiku to answer plain-English questions about the bot's commands, or to run them for you. Commands run with your own permissions, and anything that needs elevated rights waits for you to press **Run**. | `!ai`, `!myai`, `!aithread`, `!guide`, `!claude …` |
| [`gemini`](data/cogs/CogManager/cogs/gemini/) | Image generation with Google Gemini. The Claude cog calls it for "draw…" requests. | `!draw`, `!draw edit`, `!gemini …` |
| [`gamemanager`](data/cogs/CogManager/cogs/gamemanager/) | Per-server game library: tick-box pickers for the games people own and have installed, rankings, a shared-game finder, "looking for group" pings, scheduled sessions with join buttons and reminders, and votes on what to play. See its [README](data/cogs/CogManager/cogs/gamemanager/README.md). | `!games …` (aliases `game`, `gm`), `/games …` |
| [`buttongreeter`](data/cogs/CogManager/cogs/buttongreeter/) | Welcome flow for new members: alliance and role buttons, a `[TAG] Name` nickname, then agreeing to the rules. | `!bg …`, `!changerole`, `!forceclass`, `!forcerulesremove` |
| [`censord`](data/cogs/CogManager/cogs/censord/) | Word filter with `off`/`low`/`high` levels, CSV word lists, per-channel overrides, and threshold punishments (delete, kick or ban). | `!censor …` |

Not sure how to do something? Ask the bot: `!guide how do I start a game vote?`, or @mention it. You can also ask it to do things: `!guide add Rocket League to my games and mark it installed`.

### Third-party cogs (not in this repo)

These are installed on the server with Red's Downloader and updated with `!cog update`, so they aren't tracked here:

antispam, autoroom, system, easytranslate, chatchart, clearchannel, consolelogs, customhelp (loaded), and roletools, autoroler (installed but not loaded).

To change one, fork it into a new, differently named cog under `CogManager/cogs/` instead of editing the Downloader copy.

## Repository layout

```
.gitignore          whitelist: tracks only the custom cogs, docs, and backups
.gitattributes      forces LF line endings (the server is Linux)
CLAUDE.md           detailed notes for working on the bot with Claude Code
backups/            snapshots of replaced code (e.g. the old Gemini chat cog)
data/cogs/CogManager/cogs/<cog>/   our custom cogs
```

`.gitignore` ignores everything under `data/` except the custom cog folders listed in it, and never tracks a `settings.json`, even inside a cog folder. **To add a new cog**, create its folder under `data/cogs/CogManager/cogs/` and add a matching `!/data/cogs/CogManager/cogs/<name>/` line to `.gitignore`.

## Deploying

The server updates by pulling `main` in the folder that contains `data/`.

### First-time setup on the server

Run these as the user that owns `data/`:

```sh
# 1. Read-only deploy key (add the .pub contents in GitHub → Settings → Deploy keys)
ssh-keygen -t ed25519 -f ~/.ssh/red_deploy -N ""
# then point git at it, e.g. in ~/.ssh/config:
#   Host github.com
#     IdentityFile ~/.ssh/red_deploy

# 2. Adopt the existing folder without touching untracked runtime files
git init -b main
git remote add origin git@github.com:bradqui/Red.git
git fetch origin
git reset origin/main        # moves the branch only; files are unchanged
git status                   # review what differs from the repo
git diff
git reset --hard origin/main # take the repo's versions of the tracked files
```

Then, in Discord, as the bot owner:

```
!pipinstall anthropic
!pipinstall tzdata
!set api anthropic api_key,<your Anthropic key>     (delete the message afterwards)
!reload gemini
!reload gamemanager
!load claude
!slash enable games
!slash sync
```

The last two turn on the `/games` slash commands. Buttons on game sessions and votes posted before this update stop working; start new ones.

The Gemini cog needs its own key, set with `!gemini setkey <key>`, if it isn't set already.

### Updating

```sh
git pull
```

Then run `!reload <cog>` in Discord for each cog that changed. If a cog's `info.json` gains a new requirement, run `!pipinstall <package>` first.

## Development

- Edit the cogs here, then push to `main`. You can't run the bot locally: the venv in `data/venv` holds Linux binaries. To check syntax before pushing, run `python -m py_compile <file>`.
- Persist data with Red's `Config`. Never change an existing cog's Config identifier, because that orphans its saved data.
- Don't hand-edit `settings.json` while the bot is running. Red keeps the data in memory and will overwrite your edits. Change settings through bot commands instead.
- Never commit secrets. The bot token and API keys live in untracked `settings.json` files.

See [CLAUDE.md](CLAUDE.md) for the full architecture notes and per-cog quirks.
