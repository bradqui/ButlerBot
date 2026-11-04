---
title: Voice rooms
nav_order: 9
permalink: /voice/
---

# Voice rooms

Want a voice channel just for your group? Join the server's **room-maker voice channel** and ButlerBot creates one for you.

## Making a room

1. Join the source voice channel. Ask a mod which one it is if you're unsure.
2. ButlerBot creates a new channel named after you ("YourName's Room") and moves you in.
3. Invite friends. The room is deleted automatically when everyone leaves.

**Limit:** you can make up to 2 rooms a minute.

## Running your room

You're the room's owner. Use these commands while you're in it. `!vc` works in place of `!autoroom`:

| Command | What it does |
|---|---|
| `!autoroom settings` | Shows the room's owner, access, bitrate and who's allowed or denied. Anyone in the room can use it. |
| `!autoroom name <new name>` | Renames the room. Discord allows 2 renames per 10 minutes. |
| `!autoroom users <0-99>` | Sets the user limit (0 = no limit). |
| `!autoroom bitrate <kbps>` | Sets audio quality. |
| `!autoroom public` | Anyone can see and join. |
| `!autoroom locked` | Everyone can see it, but nobody new can join. People already inside can stay. |
| `!autoroom private` | Hidden and closed. People already inside can stay. |
| `!autoroom allow <member or role>` | Let someone in, even when locked or private. |
| `!autoroom deny <member or role>` | Keep someone out. They're disconnected if they're inside. |
| `!autoroom claim` | Take over a room whose owner left at least 2 minutes ago. |

**Command messages:** your command message is cleaned up after a few seconds, and ✅ means it worked.

**Editing directly:** as owner you can also edit the room through Discord itself: right-click it (long-press on mobile) → **Edit Channel**.

**Who you can't deny:** the server owner, admins, or the bot.

{: .staff }
> **Admins** set up room makers with `!autoroomset`:
> - `create <source voice channel> <category>` runs a short wizard that asks the room type and naming.
> - `modify …` changes a source later.
> - `access admin|mod` controls whether staff can enter locked rooms.
> - `permissions` checks the bot has what it needs.
>
> The bot needs **Manage Channels**, **Move Members** and **Manage Roles**.
