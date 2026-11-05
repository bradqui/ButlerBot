---
title: Reminders and auto-replies
nav_order: 8
permalink: /speakup/
---

# Reminders and auto-replies

## Reminders

```
!remindme 2h check the oven
!remindme 30m stretch
!remindme tomorrow 8am call the dentist
!remindme friday 6pm buy Helldivers
```

**Times:**
- Relative: `10m`, `2h`, `1d 3h`, `2 weeks`.
- Clock times, in your timezone: `9pm`, `tomorrow 8am`, `friday 6pm`, `11/14 7pm`.

**Delivery:** ButlerBot pings you in the same channel, or by DM if the channel is gone.

| Command | What it does |
|---|---|
| `!reminders` | List yours. |
| `!reminders cancel <id>` | Cancel one. |
| `!reminders clear` | Cancel all of yours. |

You can also ask: `!butler remind me friday at 6 to buy Helldivers`.

## When ButlerBot chimes in on its own

ButlerBot sometimes offers help without being asked. Its replies never ping anyone, and each has a 🗑️ (Remove) button. It deletes the reply **for everyone**, after a quick confirmation only you see. It works for the person the reply was for, and for mods.

| You post… | ButlerBot… |
|---|---|
| A time while making plans ("anyone up for 9?", "friday 8pm?") | Adds a 🕘 reaction. Click it for a small card with the time in everyone's own timezone and a **Schedule a session** button. |
| A Steam store link | Replies with a small card: the price and any sale, who here owns or wants it, and **I own it** / **Add to wishlist** buttons. The card updates when someone clicks. |
| An article or video link | Adds a 📄 reaction. Click it for a three-line summary, posted in the channel. |
| A command that doesn't exist | Suggests the one you probably meant, with a **Run it** button. **Run it** works for 5 minutes, for the person who typed the command. |

**Reactions are offers:** nothing happens unless someone clicks.

**Want a summary just for you?** Right-click any message with a link (long-press on mobile) → **Apps** → **Summarize link**. Only you see the result, and nothing is posted in the channel.

**Limits:**
- 🕘 at most once every few minutes per channel. 📄 goes on every link it can summarize.
- Steam cards once per game per channel every few hours.
- 10 summaries per person per hour.

## Turning it off

| Command | Effect | Who |
|---|---|---|
| `!speakup` | Shows what's on here. | Everyone |
| `!speakup me off` / `on` | No reactions, cards or suggestions on **your** messages. | Everyone |
| `!speakup off [#channel]` / `on` | Quiet in a channel. Commands and reminders still work. | Mods |
| `!speakup feature <times\|steam\|links\|mistakes> <on\|off>` | Switch one feature off server-wide. | Admins |
