---
title: Server stats
nav_order: 7
permalink: /stats/
---

# Server stats

See how the server is doing: which channels are busy, when people are around, who's in voice, and what everyone's playing.

| Command | What it shows |
|---|---|
| `!stats [period]` | The last week at a glance: messages, busiest channels and hour, voice time, top game. |
| `!stats channels [period]` | Messages per day in each channel, with a chart. |
| `!stats channel [#channel] [period]` | One channel: daily activity, busiest day and hour, top posters. |
| `!stats top [#channel] [period]` | Leaderboard of who posted the most (aliases `leaderboard`, `lb`). |
| `!stats heatmap [#channel] [period]` | A day-by-hour chart of when it's busiest, in your timezone. Handy for picking game night times. |
| `!stats voice [period]` | Time in each voice channel, who's there most, and the most people at once. |
| `!stats games [period]` | The most-played games, from Discord's "Playing" status. |
| `!stats me [period]` | Your own numbers. It also suggests adding games you play often to your library. |

**Periods** look like `week`, `month`, `year`, `90d`, `2 weeks` or `all`. For example: `!stats top week`, `!stats heatmap #general month`.

Or ask in plain English: `!butler when is voice busiest?`

## Privacy

- ButlerBot keeps **hourly counts** per person and channel: no message text, ever.
- You only see stats for channels you can open, so private and staff channels stay private.
- Bots aren't counted.
- **Opting out:** `!stats ignoreme` stops tracking you everywhere and deletes what's been recorded. `!stats trackme` turns it back on.
- **Games played** come from your Discord activity status. If you've hidden your activity, nothing is recorded.

{: .staff }
> **Admin reports** (`!stats admin …`):
> - `active`: daily, weekly and monthly active members
> - `retention`: do new members post and stick around?
> - `quiet`: lurkers, and members who went quiet
> - `joins`: joins and leaves
> - `deadchannels`
> - `attendance`: game sessions, who joined vs. who showed up in voice
> - `commands`: what's used, what isn't, and commands people typed that don't exist
> - `unmet`: questions the butler couldn't answer
> - `libraries`: who has set up a game library
>
> **Settings:**
> - `!stats admin digest on|off|channel #ch|time monday 9am|preview` is a weekly summary for an admin channel.
> - `exclude` / `include #channel` controls what's tracked; `gametracking on|off` controls game tracking.
> - `backfill <days>` counts messages from before tracking started.
