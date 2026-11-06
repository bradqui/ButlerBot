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
| `!games top [installed] [shared]` | The channel's favorites, by everyone's rankings, with how many own and have installed each one. Page through with ◀ ▶. |
| `!games whoowns <game>` / `!games whoinstalled <game>` | Who has a game. |
| `!games lfg <game>` | Pings everyone who has the game installed ("looking for group"). Once per 5 minutes. |

Or just ask: `!butler what do Alex, Sam and I all have installed?`

## Sessions

A session is a post people join with a button. Start one now, or schedule it:

```
!session new                            starts now
!session new Raid night                 with a title
!session new friday 9pm Raid night      scheduled
!session new in 2h Rocket League
!session new tomorrow 8:30pm
```

**The session commands at a glance:**

| Command | What it does |
|---|---|
| `!session` | Brings this channel's session card down to you. |
| `!session new [time] [title]` | Starts a session. |
| `!session join [name]` / `!session leave [name]` | Join or leave without finding the card. Add its name if there's more than one. |
| `!session vote [picks] [time]` | Starts the vote (host or game admin). |
| `!session end [name]` | Ends it (host or game admin). |
| `!sessions` | Lists the active sessions, with links to their cards. |

These are short for the `!games …` versions (`!games session`, `!games join`, `!games here`, …), which work too.

**Times:**
- Times are read in your timezone (`!games timezone`), and everyone sees them in their own.
- Accepted forms: `9pm`, `9:30 pm`, `21:00`, `tonight 9pm`, `friday 9pm`, `11/14 7pm`, `in 1h30m`, or a pasted Discord timestamp.

**What happens next:**
- The post is a card that shows the start time (in everyone's own timezone) and who's playing. Players press **Join** (or **Leave**).
- The whole game night happens in that one card: the vote and its result show up in it too, so there's one place to look.
- Everyone who joined gets a ping 15 minutes before and another at the start. If the card is still in view, the ping is one line with a link back to it.
- If you haven't set a timezone, the card says which one your time was read in, with how to fix it.
- Sessions end on their own 12 hours after they start. An ended session's card turns grey and loses its buttons, and its pings are cleaned up.

**When chatter buries the card:**
- The card moves itself to the bottom of the channel for the 15-minute reminder, the start and a vote, and pings players there instead of in a separate line. It only moves once it has 10 or more messages below it.
- `!session` (or `!games here`) brings it down any time, once a minute per channel. Add the session's name if the channel has more than one: `!session here Raid night`.
- `!session join` and `!session leave` work without the card. With more than one session around, add its name: `!session join Raid night`.
- The slash versions (`/games join`, `/games leave`, `/games here`) answer just to you and list the sessions as you type.

**Discord events:**
- Scheduled sessions also show up in the server's **Events** list.
- Pressing **Interested** there joins the session too, and Discord reminds you.
- **Give the event details when you start the session:**
  - `/games session` has optional fields for a description, a banner image, a voice channel and a length (like `2h`).
  - With `!session new`, attach an image for the banner, mention a voice channel to hold it there, and put a description on the lines below (Shift+Enter for a new line). A `Length:` line sets how long the event runs:
    ```
    !session new friday 9pm Raid night #Raid Voice
    Bring a mic. We're starting the new raid.
    Length: 3h
    ```
  - Asking the AI works too: "`!ai` set up a weekly session on Fridays at 9pm in #Raid Voice, banner attached". Attach the image to that message and mention the channel with `#`.
- **The banner shows on the session card too,** full width across the top, the same picture as the event.
- **Change them later** with the session card's **✏️ Edit event** button (host or game admin): description, length, voice channel and banner, or remove the banner. You don't need Discord's Manage Events permission for this.
- **Weekly sessions:** each week's session is its own event, posted a day ahead (not one repeating Discord event, so each week has its own Interested list, card and details). Details set when you create the weekly session are used every week. In **Edit event**, tick **Also use for future sessions** to change every week from then on; otherwise only that week changes.
- **Edited the event in Discord instead?** That works too: a new time, name or voice channel carries over to the session card and its reminders, and cancelling the event ends the session. It only changes that one week's session.

{: .tip }
> Someone wrote "let's play at 9" in chat? Click the 🕘 that ButlerBot adds to the message. It shows the time in your timezone, with a **Schedule a session** button.

### Weekly game nights

```
!session new every friday 9pm Raid night
!session new every other sunday 8pm
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
!session vote             1 pick each, 2 minutes
!session vote 2 3m        2 picks each, 3 minutes
```

**The options:** games everyone has installed. If there are none, games everyone owns; failing that, games at least two players have installed.

**How it runs:**
- The session card switches to voting: the games appear as buttons inside it, each showing its votes so far, with how many have voted, who's still to vote, and when voting ends.
- Everyone in the session gets a one-line ping linking to the card. It's deleted when the vote ends.
- Press a game to vote. Press it again to take the vote back.
- The vote ends when everyone has voted or time runs out.
- The result stays in the card: the 🏆 winner and how many votes each game got. Players get a one-line ping with the winner.
- **Want to switch games later?** Start another vote. Every game is an option again, including the one you're playing, so if most people want to stay, it wins. The card keeps a history of the winners: "Earlier: Deep Rock Galactic (won twice)".
- **Ties** go to the game the players rank higher, then to a random pick.
- Only people who joined before the vote started can vote.

| Command | What it does |
|---|---|
| `!games results [vote id]` | The tally so far. |
| `!games endvote [vote id]` | End now and announce the winner. |
| `!sessions` | Active sessions, with links. |
| `!session end [name]` | End your latest session here, or one by name (host or game admin). |

The IDs are optional: without one, these use the latest vote in the channel.

{: .staff }
> **Game admins:**
> - `!games admin clearsessions` and `clearvotes` clean up.
> - `!games admin events true|false` turns Discord events on or off.
> - `!games admin eventchannel <voice channel>` points events at your usual voice room.
>
> Discord events need the bot to have **Manage Events**.
