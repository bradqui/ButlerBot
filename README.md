# ButlerBot

Custom cogs and deployment setup for ButlerBot, our [Red-DiscordBot](https://github.com/Cog-Creators/Red-DiscordBot) instance.

The repo mirrors the bot's data directory (`data/`, mounted at `/data` in the Docker container), but only our own code is tracked. Everything else in `data/` is runtime state that stays on the server: the bot token, API keys, per-server settings, logs, the Python venv, and the third-party cogs.

**Runtime:** Red 3.5.24 · discord.py 2.7.1 · Python 3.11 · Docker (`phasecorex/red-discordbot`) · JSON storage · prefix `!`

## Custom cogs

All of them live in [`data/cogs/CogManager/cogs/`](data/cogs/CogManager/cogs/).

| Cog | What it does | Main commands |
|---|---|---|
| [`claude`](data/cogs/CogManager/cogs/claude/) | AI chat with Anthropic's Claude (Sonnet 5.5 by default). It has one shared conversation per channel, plus AI threads. Replying to an answer continues the conversation. It reads images, PDFs, and text files, can search the web and cite sources, and tracks usage and cost, with optional daily limits. Image requests are handed to Gemini. The same AI answers plain-English questions about the bot (`!butler` is the same as `!ai`), looking up the exact commands, or runs them for you. Commands run with your own permissions, and anything that needs elevated rights waits for you to press **Run**. `/catchup` summarizes a channel since you last spoke, only for you. | `!ai`, `!aithread`, `!butler` (alias `!guide`), `/catchup`, `!catchup`, `!claude …` |
| [`gemini`](data/cogs/CogManager/cogs/gemini/) | Image generation with Google Gemini. The Claude cog calls it for "draw…" requests. | `!draw`, `!draw edit`, `!gemini …` |
| [`gamemanager`](data/cogs/CogManager/cogs/gamemanager/) | Per-server game library and game nights:<br>- tick-box pickers for the games people own and have installed, and a step-by-step profile setup<br>- rankings, a shared-game finder, and "looking for group" pings<br>- scheduled and weekly sessions with join buttons, reminders and Discord events<br>- votes on what to play<br>- wishlists with Steam sale alerts<br><br>See its [README](data/cogs/CogManager/cogs/gamemanager/README.md). | `!games …` (aliases `game`, `gm`), `/games …` |
| [`activitystats`](data/cogs/CogManager/cogs/activitystats/) | Server activity stats. Everyone sees messages per channel, leaderboards, a heatmap of busy times, voice time, most-played games and their own stats. Admins get active-member trends, new-member retention, quiet members, joins and leaves, dead channels, game-night attendance, command usage, unanswered guide questions, library coverage and an optional weekly digest. Stores hourly counts, never message text; members can opt out. The butler and AI chat can answer stats questions. | `!stats …`, `!stats admin …` |
| [`speakup`](data/cogs/CogManager/cogs/speakup/) | The bot chiming in when it can help:<br>- a clock reaction on times in chat (click it to see the time in everyone's timezone and schedule a session)<br>- cards for Steam store links (price, sale, who owns it, add and wishlist buttons)<br>- a summary offer on article links<br>- "did you mean…" for mistyped commands<br><br>Also reminders. Quiet it per channel, per person or per feature. | `!speakup …`, `!remindme`, `!reminders` |
| [`parlor`](data/cogs/CogManager/cogs/parlor/) | Games and fun on top of the Claude cog:<br>- `!guessgame`: Gemini paints a game from the server's library and the first correct guess wins<br>- `!emojigame`: guess the game from a row of emoji<br>- `!twentyq`: twenty questions about a game, in a thread<br>- `!adventure`: a group text adventure in a thread<br>- `!judge`: ButlerBot settles an argument in character<br>- `!critique`: a gallery critic's review of a screenshot<br>- `!roast`: a roast of a game library (others only if they opted in)<br>- `!mystery`: Murder at the Manor, solved by questioning suspects with `!interrogate`<br>- `!caption`: a caption contest for a screenshot or a drawn picture, judged by votes and the Butler<br>- `!maketrivia`: writes a list for Red's trivia game | `!parlor`, `!guessgame`, `!emojigame`, `!twentyq`, `!adventure`, `!judge`, `!critique`, `!roast`, `!mystery`, `!interrogate`, `!accuse`, `!caption`, `!maketrivia` |
| [`estate`](data/cogs/CogManager/cogs/estate/) | The bot owner's view of every server, in DMs: members and this month's AI spend per server, a monthly budget for the whole bot and per server (DM alerts at 50/80/100%, AI pauses at 100%), a remote AI switch, a DM with a Leave button when the bot joins a new server, and health (background tasks, recent errors, missing permissions). Numbers only. | `!estate` (owner) |
| [`handbook`](data/cogs/CogManager/cogs/handbook/) | Replaces `!help` with short cards that link to the [online handbook](https://bradqui.github.io/ButlerBot/), whose pages live in [`docs/`](docs/). `!handbook [topic]` posts links. The owner's `!handbook export` generates the command reference from the running bot. | `!help`, `!handbook` |
| [`buttongreeter`](data/cogs/CogManager/cogs/buttongreeter/) | Welcome flow for new members: alliance and role buttons, a `[TAG] Name` nickname, then agreeing to the rules. | `!bg …`, `!changerole`, `!forceclass`, `!forcerulesremove` |
| [`censord`](data/cogs/CogManager/cogs/censord/) | Word filter with `off`/`low`/`high` levels, CSV word lists, per-channel overrides, and threshold punishments (delete, kick or ban). | `!censor …` |

**User handbook:** <https://bradqui.github.io/ButlerBot/>, built from [`docs/`](docs/) with GitHub Pages. In Discord, `!help` and `!handbook` link to it.

Not sure how to do something? Ask the bot: `!butler how do I start a game vote?`, or @mention it. You can also ask it to do things: `!butler add Rocket League to my games and mark it installed`.

### Third-party cogs (not in this repo)

These are installed on the server with Red's Downloader and updated with `!cog update`, so they aren't tracked here:

antispam, autoroom, system, easytranslate, chatchart, clearchannel and consolelogs (loaded); customhelp (unloaded: the handbook cog replaces it); roletools and autoroler (installed but not loaded).

To change one, fork it into a new, differently named cog under `CogManager/cogs/` instead of editing the Downloader copy.

## Repository layout

```
.gitignore          whitelist: tracks only the custom cogs and docs
.gitattributes      forces LF line endings (the server is Linux)
CLAUDE.md           detailed notes for working on the bot with Claude Code
LICENSE             MIT
docs/               the user handbook (GitHub Pages, Jekyll + just-the-docs)
tests/              offline tests (stubbed Red, real discord.py); run on every push by .github/workflows
tools/              build_reference.py (the handbook's command reference), reload_hint.py (deploy steps)
data/cogs/CogManager/cogs/<cog>/   our custom cogs
```

`.gitignore` ignores everything under `data/` except the custom cog folders listed in it, and never tracks a `settings.json`, even inside a cog folder. **To add a new cog**, create its folder under `data/cogs/CogManager/cogs/` and add a matching `!/data/cogs/CogManager/cogs/<name>/` line to `.gitignore`.

## Deploying

The server runs the bot in Docker. It updates by pulling `main` in the folder that contains `data/`. The repo is public, so pulling needs no key.

### First-time setup on the server

Run these as the user that owns `data/`, in the folder that contains it. They adopt the existing folder without touching the untracked runtime files:

```sh
git init -b main
git remote add origin https://github.com/bradqui/ButlerBot.git
git fetch origin
git reset origin/main          # moves the branch only; files are unchanged
git status                     # review what differs from the repo
git diff
git reset --hard origin/main   # take the repo's versions of the tracked files
git branch --set-upstream-to=origin/main main
```

Then, in Discord, as the bot owner. Delete the messages containing keys afterwards.

```
!pipinstall anthropic
!pipinstall tzdata
!set api anthropic api_key,<your Anthropic key>
!gemini setkey <your Gemini key>
!unload customhelp
!load claude
!load gemini
!load gamemanager
!load activitystats
!load speakup
!load parlor
!load estate
!load handbook
!load buttongreeter
!load censord
!slash enable games
!slash enable catchup
!slash enable "Summarize link" message
!slash sync
```

**Notes on that list:**
- **`!unload customhelp` first:** the handbook cog replaces `!help`, and only one cog can do that.
- **Already-loaded cogs:** use `!reload <cog>` instead of `!load`.
- **After each `git pull`:** `python3 tools/reload_hint.py` prints exactly what to run in Discord (unload, install, load, reload, slash sync), in order.
- **Bot permissions:** besides the usual ones, the bot needs **Manage Events** (session events) and **Add Reactions** (time and link offers).
- **Command reference:** `!handbook export` generates it for [`docs/reference/`](docs/reference/).

### Updating

```sh
git pull
```

Then run `!reload <cog>` in Discord for each cog that changed. If a cog's `info.json` gains a new requirement, run `!pipinstall <package>` first. A brand-new cog needs `!load <cog>` once instead of `!reload`.

## Development

- Edit the cogs here, then push to `main`. You can't run the bot locally: the venv in `data/venv` holds Linux binaries. To check syntax before pushing, run `python -m py_compile <file>`.
- **Tests:** `python -m pip install -r tests/requirements.txt`, then `python tests/run_all.py` (or `python tests/run_all.py parlor` for some). They need no Discord connection or Red install. GitHub runs them on Python 3.11 for every push to `main`; the Actions tab shows the results.
- Persist data with Red's `Config`. Never change an existing cog's Config identifier, because that orphans its saved data.
- Don't hand-edit `settings.json` while the bot is running. Red keeps the data in memory and will overwrite your edits. Change settings through bot commands instead.
- Never commit secrets. The bot token and API keys live in untracked `settings.json` files.

See [CLAUDE.md](CLAUDE.md) for the full architecture notes and per-cog quirks.

## Using these cogs on your own bot

They were written for this server, but they're ordinary Red 3.5 cogs, and you're welcome to borrow them under the MIT license. This repo isn't laid out as a Downloader repo, so install by hand:

1. Copy a cog's folder into your bot's cog path (`[p]paths` shows it).
2. Install its `info.json` requirements with `[p]pipinstall`.
3. `[p]load` it.

Some cogs build on others:
- `parlor` and parts of `speakup` need `claude`.
- Session scheduling, Steam cards and `guessgame` need `gamemanager`. The parlor games use its library when it has at least 3 games.
- `guessgame` also needs `gemini`.
- Everything degrades gracefully when a partner cog is missing.

## License

MIT, see [LICENSE](LICENSE). The vendored `typing_extensions` in `data/cogs/CogManager/cogs/gemini/lib/` keeps its own license (PSF).
