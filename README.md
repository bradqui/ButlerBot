# ButlerBot

Custom cogs and deployment setup for ButlerBot, our [Red-DiscordBot](https://github.com/Cog-Creators/Red-DiscordBot) instance.

The repo mirrors the bot's data directory (`data/`, mounted at `/data` in the Docker container), but only our own code is tracked. Everything else in `data/` is runtime state that stays on the server: the bot token, API keys, per-server settings, logs, the Python venv, and the third-party cogs.

**Runtime:** Red 3.5.24 · discord.py 2.7.1 · Python 3.11 · Docker (`phasecorex/red-discordbot`) · JSON storage · prefix `!`

## Custom cogs

All of them live in [`data/cogs/CogManager/cogs/`](data/cogs/CogManager/cogs/).

| Cog | What it does | Main commands |
|---|---|---|
| [`claude`](data/cogs/CogManager/cogs/claude/) | AI chat with Anthropic's Claude (Sonnet 5.5 by default). It has shared channel conversations, private conversations, and AI threads. Replying to an answer continues the conversation. It reads images, PDFs, and text files, can search the web and cite sources, and tracks usage and cost, with optional daily limits. Image requests are handed to Gemini. It also includes **the butler**, a guide that uses Haiku to answer plain-English questions about the bot's commands, or to run them for you. Commands run with your own permissions, and anything that needs elevated rights waits for you to press **Run**. | `!ai`, `!myai`, `!aithread`, `!butler` (alias `!guide`), `!claude …` |
| [`gemini`](data/cogs/CogManager/cogs/gemini/) | Image generation with Google Gemini. The Claude cog calls it for "draw…" requests. | `!draw`, `!draw edit`, `!gemini …` |
| [`gamemanager`](data/cogs/CogManager/cogs/gamemanager/) | Per-server game library: tick-box pickers for the games people own and have installed, rankings, a shared-game finder, "looking for group" pings, scheduled sessions with join buttons and reminders, and votes on what to play. See its [README](data/cogs/CogManager/cogs/gamemanager/README.md). | `!games …` (aliases `game`, `gm`), `/games …` |
| [`activitystats`](data/cogs/CogManager/cogs/activitystats/) | Server activity stats. Everyone sees messages per channel, leaderboards, a heatmap of busy times, voice time, most-played games and their own stats. Admins get active-member trends, new-member retention, quiet members, joins and leaves, dead channels, game-night attendance, command usage, unanswered guide questions, library coverage and an optional weekly digest. Stores hourly counts, never message text; members can opt out. The butler and AI chat can answer stats questions. | `!stats …`, `!stats admin …` |
| [`speakup`](data/cogs/CogManager/cogs/speakup/) | The bot chiming in when it can help:<br>- a clock reaction on times in chat (click it to see the time in everyone's timezone and schedule a session)<br>- cards for Steam store links (price, sale, who owns it, add and wishlist buttons)<br>- a summary offer on article and video links<br>- "did you mean…" for mistyped commands<br><br>Also reminders. Quiet it per channel, per person or per feature. | `!speakup …`, `!remindme`, `!reminders` |
| [`butlerfun`](data/cogs/CogManager/cogs/butlerfun/) | AI extras on top of the Claude cog:<br>- `/catchup`: a summary of a channel since you last spoke, only for you<br>- `!judge`: ButlerBot settles an argument in character<br>- `!adventure`: a group text adventure in a thread<br>- `!maketrivia`: writes a list for Red's trivia game<br>- `!guessgame`: Gemini paints a game from the server's library and the first correct guess wins | `/catchup`, `!catchup`, `!judge`, `!adventure`, `!maketrivia`, `!guessgame` |
| [`handbook`](data/cogs/CogManager/cogs/handbook/) | Replaces `!help` with short cards that link to the [online handbook](https://bradqui.github.io/ButlerBot/), whose pages live in [`docs/`](docs/). `!handbook [topic]` posts links. The owner's `!handbook export` generates the command reference from the running bot. | `!help`, `!handbook` |
| [`buttongreeter`](data/cogs/CogManager/cogs/buttongreeter/) | Welcome flow for new members: alliance and role buttons, a `[TAG] Name` nickname, then agreeing to the rules. | `!bg …`, `!changerole`, `!forceclass`, `!forcerulesremove` |
| [`censord`](data/cogs/CogManager/cogs/censord/) | Word filter with `off`/`low`/`high` levels, CSV word lists, per-channel overrides, and threshold punishments (delete, kick or ban). | `!censor …` |

**User handbook:** <https://bradqui.github.io/ButlerBot/>, built from [`docs/`](docs/) with GitHub Pages. In Discord, `!help` and `!handbook` link to it.

Not sure how to do something? Ask the bot: `!butler how do I start a game vote?`, or @mention it. You can also ask it to do things: `!butler add Rocket League to my games and mark it installed`.

### Third-party cogs (not in this repo)

These are installed on the server with Red's Downloader and updated with `!cog update`, so they aren't tracked here:

antispam, autoroom, system, easytranslate, chatchart, clearchannel, consolelogs, customhelp (loaded), and roletools, autoroler (installed but not loaded).

To change one, fork it into a new, differently named cog under `CogManager/cogs/` instead of editing the Downloader copy.

## Repository layout

```
.gitignore          whitelist: tracks only the custom cogs and docs
.gitattributes      forces LF line endings (the server is Linux)
CLAUDE.md           detailed notes for working on the bot with Claude Code
LICENSE             MIT
docs/               the user handbook (GitHub Pages, Jekyll + just-the-docs)
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
git remote add origin git@github.com:bradqui/ButlerBot.git
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

Then run `!reload <cog>` in Discord for each cog that changed. If a cog's `info.json` gains a new requirement, run `!pipinstall <package>` first. A brand-new cog needs `!load <cog>` once instead of `!reload`.

## Development

- Edit the cogs here, then push to `main`. You can't run the bot locally: the venv in `data/venv` holds Linux binaries. To check syntax before pushing, run `python -m py_compile <file>`.
- Persist data with Red's `Config`. Never change an existing cog's Config identifier, because that orphans its saved data.
- Don't hand-edit `settings.json` while the bot is running. Red keeps the data in memory and will overwrite your edits. Change settings through bot commands instead.
- Never commit secrets. The bot token and API keys live in untracked `settings.json` files.

See [CLAUDE.md](CLAUDE.md) for the full architecture notes and per-cog quirks.

## License

MIT, see [LICENSE](LICENSE). The vendored `typing_extensions` in `data/cogs/CogManager/cogs/gemini/lib/` keeps its own license (PSF).
