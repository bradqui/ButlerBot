---
title: Game nights
parent: Games
nav_order: 2
permalink: /games/nights/
---

# Game nights

## Finding something to play

| Command | What it does |
|---|---|
| `!games shared [members…]` | Games everyone named owns. With no names, uses everyone in the channel who has a library. |
| `!games installed [members…]` | Games everyone named has installed, ready to go. |
| `!games top [installed] [shared]` | The channel's favorites, by everyone's rankings. |
| `!games whoowns <game>` / `!games whoinstalled <game>` | Who has a game. |
| `!games lfg <game>` | Pings everyone who has the game installed ("looking for group"). Once per 5 minutes. |

Or just ask: `!butler what do Alex, Sam and I all have installed?`

## Sessions

A session is a post people join with a button. Start one now, or schedule it:

```
!games session                          starts now
!games session Raid night               with a title
!games session friday 9pm Raid night    scheduled
!games session in 2h Rocket League
!games session tomorrow 8:30pm
```

**Times:**
- Times are read in your timezone (`!games timezone`), and everyone sees them in their own.
- Accepted forms: `9pm`, `9:30 pm`, `21:00`, `tonight 9pm`, `friday 9pm`, `11/14 7pm`, `in 1h30m`, or a pasted Discord timestamp.

**What happens next:**
- Players press **Join** (or **Leave**).
- Everyone who joined gets a reminder 15 minutes before and a ping at the start.
- Sessions end on their own 12 hours after they start.

**Discord events:**
- Scheduled sessions also show up in the server's **Events** list.
- Pressing **Interested** there joins the session too, and Discord reminds you.

{: .tip }
> Someone wrote "let's play at 9" in chat? Click the 🕘 that ButlerBot adds to the message. It shows the time in your timezone, with a **Schedule a session** button.

### Weekly game nights

```
!games session every friday 9pm Raid night
!games session every other sunday 8pm
```

**How they work:**
- Each one is posted a day before it starts.
- It stays at the same local time across daylight saving changes.

**Managing them:**
- `!games recurring` lists them.
- The host or a game admin can `!games recurring skip <id>` the next one, or `!games recurring stop <id>`.

## Voting on what to play

When everyone's in, the host presses **Start vote** on the session, or runs:

```
!games vote               1 pick each, 2 minutes
!games vote 2 3m          2 picks each, 3 minutes
```

**The options:** games everyone has installed. If there are none, games everyone owns; failing that, games at least two players have installed.

**How it runs:**
- Press a game to vote. Press it again to take the vote back.
- The vote ends when everyone has voted or time runs out.
- **Ties** go to the game the players rank higher, then to a random pick.

| Command | What it does |
|---|---|
| `!games results [vote id]` | The tally so far. |
| `!games endvote [vote id]` | End now and announce the winner. |
| `!games sessions` | Active sessions, with links. |
| `!games endsession [session id]` | End your latest session here (host or game admin). |

{: .staff }
> **Game admins:**
> - `!games admin clearsessions` and `clearvotes` clean up.
> - `!games admin events true|false` turns Discord events on or off.
> - `!games admin eventchannel <voice channel>` points events at your usual voice room.
>
> Discord events need the bot to have **Manage Events**.
