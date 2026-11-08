---
title: Server setup
nav_order: 22
permalink: /admin/
---

# Server setup
{: .no_toc }

For admins: a checklist for a new server, who can use what, custom commands, the welcome flow, and where each feature's settings live.

1. TOC
{:toc}

## New server checklist

When ButlerBot joins a server, work through these steps in order. Every step after the first is optional: ButlerBot works without it, just with less.

### 1. Give the bot its permissions

Give ButlerBot's role these permissions server-wide. A missing one usually shows up later as an error in a single feature.

| Permission | What needs it |
|---|---|
| View Channels, Send Messages, Embed Links, Attach Files, Read Message History, Add Reactions | Everything: replies and cards, stats charts, calendar files, the 🕘 and 📄 reactions, and stats backfill |
| Create Public Threads, Send Messages in Threads | Game threads: guess the game, the emoji game, twenty questions, adventures, mysteries and caption chats. Without them, the guessing games play in the channel instead. |
| Manage Events | Discord events for game nights |
| Manage Roles, Manage Nicknames | The welcome flow: group roles, the rules role, and `[TAG]` nicknames. Move ButlerBot's role **above** the roles it gives out and the members it renames. |
| Manage Messages | The word filter, and `!cleanup` |
| Kick Members, Ban Members | Moderation, and the word filter's kick and ban actions |
| Manage Channels, Move Members | Voice rooms (`!autoroomset permissions` checks what they need) |

### 2. Staff roles

```
!set roles addmodrole @Moderators
!set roles addadminrole @Admins
!games admin setrole @Game Admins     optional: who approves games and runs any session
```

### 3. Welcome flow

```
!bg setchannel #welcome
!bg addrole @Raiders Raiders          one per group button: the role, then the button's label
!bg setruleschannel #rules
!bg setrulesrole @Member
!bg setadminchannel #bot-log          where problems are reported
!bg settings
```

More in [Welcome flow](#welcome-flow-buttongreeter) below.

### 4. Game nights

```
!games admin timezone America/Los_Angeles   the default for session times
!games admin sales #game-deals              wishlist sale alerts (off until a channel is set)
!games admin freegames true                 optional: free Epic games in the same channel
!games admin memberadd true                 optional: members add games without a request
!games admin settings
```

Discord events are on by default. `!games admin eventchannel "Game Night"` makes them voice-channel events instead. See [Game nights]({{ '/games/nights/' | relative_url }}).

### 5. AI chat

```
!claude settings
!claude limit 30                 optional: AI messages a day per member (mods and admins aren't limited)
!claude guidementions on         whether @ButlerBot and replies to it go to the AI chat
!claude guideactions on          whether the AI can run commands for people
!claude persona <text>           optional: your own personality instead of ButlerBot's
```

See [AI chat and images]({{ '/ai/' | relative_url }}) and [What uses AI]({{ '/ai-use/' | relative_url }}).

{: .note }
> **The bot owner** gets a DM when ButlerBot joins a new server, with a button to leave it. With `!estate cap <server> <amount>` they can set that server a monthly AI budget, and with `!estate ai <server> off` they can switch its AI off.

### 6. Auto-replies and stats

```
!speakup                            what's switched on
!speakup off #serious-talk          quiet in one channel
!speakup feature links off          one feature off everywhere (times, steam, links, mistakes)
!stats admin exclude #staff         keep a channel out of stats
!stats admin backfill 30            count the last 30 days of messages
!stats admin digest channel #stats
!stats admin digest on              a weekly summary in that channel
```

### 7. Extras

All optional:

```
!caption weekly #general            a weekly caption contest
!mystery weekly #general            a weekly murder mystery
!parlor threads off                 in a channel where games shouldn't make threads
!autoroomset create "Join to Create" "Voice Rooms"    voice rooms
!censor level low                   the word filter
```

See [Fun and games]({{ '/fun/' | relative_url }}), [Voice rooms]({{ '/voice/' | relative_url }}) and [Filters and spam]({{ '/filters/' | relative_url }}).

### 8. Check it

```
!games admin settings
!claude settings
!bg settings
!speakup
!parlor settings
!stats admin settings
```

Then run `!games newprofile` yourself to see what members see, and point everyone to [Getting started]({{ '/start/' | relative_url }}).

{: .note }
> **Slash commands** belong to the bot, not to a server, so the bot owner turns them on once for every server: `!slash enable games`, `!slash enable catchup`, `!slash enable "Summarize link" message`, then `!slash sync`. See [Slash commands](#slash-commands).

## Staff roles

The server owner tells the bot which roles are mods and admins:

```
!set roles addmodrole @Moderators
!set roles addadminrole @Admins
!set showsettings
```

Admins can do everything mods can. Many commands also accept a Discord permission instead, such as Manage Messages.

## Who can use what (Permissions)

Rules widen or narrow access to any command or whole cog, for users, roles or channels. You need to be the server owner or have Administrator.

```
!permissions addserverrule allow cleanup @Helpers      Helpers can use !cleanup
!permissions addserverrule deny Trivia #general        no trivia in #general
!permissions setdefaultserverrule deny Parlor          off unless allowed
!permissions canrun @someone guessgame                 check someone's access
!permissions explain
```

**How rules are matched:**
- Command and cog names are case-sensitive: cogs use their title-case names (`Trivia`, `GameManager`).
- The most specific rule wins, in this order: user, voice channel, channel, category, then roles (highest first).
- `!permissions acl getserver` and `!permissions acl setserver` export and import all rules as YAML.

**Turning things off entirely:**
- `!command disable <command>` / `!command enable <command>`
- `!command disablecog <Cog>` / `!command enablecog <Cog>`
- `!ignore channel [#channel]` stops the bot answering commands in a channel.

## Custom commands and aliases

**Custom commands** reply with text you set (mods):

```
!cc create rules Please read #rules before posting!
!cc create random hype          (the bot asks for several replies; one is picked at random)
!cc list
!cc delete rules
```

Replies can include placeholders like `{author.mention}`, `{channel}` or `{0}` for the first word typed after the command. See [Red's guide](https://docs.discord.red/en/stable/cog_customcom.html).

**Aliases** are shortcuts for longer commands (mods):

```
!alias add own games own        now "!own Deadlock" works
!alias list
```

When the server has some, the [command reference]({{ '/reference/' | relative_url }}) lists them on a Custom commands page.

## Self-assignable roles

```
!selfroleset add @Raiders @Builders     admin or Manage Roles
!selfrole list                          anyone
!selfrole Raiders                       anyone; toggles it
```

## Welcome flow (ButtonGreeter)

New members get buttons to pick their group, which tags their nickname as `[TAG] Name` (replacing any tag they already had), and then agree to the rules.

- Only the welcome message pings the newcomer. The rules prompt mentions them without a second ping.
- The buttons keep working after a bot restart. Welcome messages posted before the 2026-11 update don't, so use `!forceclass` for those members.
- Pressing **No** on the rules leaves the prompt up, so they can change their mind.
- If no rules role is set, members skip the rules step and the error channel gets a note.
- When something fails (a role the bot can't give, a nickname it can't change), the member gets a private explanation and the error channel gets the details.

| Command | What it sets |
|---|---|
| `!bg setchannel <#channel>` | Where newcomers are greeted |
| `!bg addrole <role> <button label>` / `removerole <label>` | The group buttons |
| `!bg setruleschannel <#channel>` / `setrulesrole <role>` | The rules and the role given after agreeing |
| `!bg setadminchannel <#channel>` | Where errors are reported |
| `!bg addmodrole <role>` / `removemodrole <role>` | Who can use `!forceclass` and `!forcerulesremove` |
| `!bg settings` | Show it all |

Members fix their own group with `!changerole <button label>`.

## Feature settings at a glance

| Feature | Settings | Covered in |
|---|---|---|
| AI chat, persona, limits, butler | `!claude …` | [AI chat]({{ '/ai/' | relative_url }}), [Asking ButlerBot]({{ '/butler/' | relative_url }}) |
| Images | `!gemini …` | [AI chat]({{ '/ai/' | relative_url }}) |
| Games, sessions, sale alerts, events | `!games admin …` | [Your games]({{ '/games/library/' | relative_url }}), [Game nights]({{ '/games/nights/' | relative_url }}) |
| Stats, weekly digest | `!stats admin …` | [Server stats]({{ '/stats/' | relative_url }}) |
| Auto-replies | `!speakup …` | [Reminders and auto-replies]({{ '/speakup/' | relative_url }}) |
| Voice rooms | `!autoroomset …` | [Voice rooms]({{ '/voice/' | relative_url }}) |
| Word filters | `!censor …`, `!filter …` | [Filters and spam]({{ '/filters/' | relative_url }}) |
| Moderation, mod log, automod | `!modset …`, `!modlogset …`, `!muteset …`, `!warningset …` | [Moderation]({{ '/moderation/' | relative_url }}) |
| Trivia | `!triviaset …` | [Fun and games]({{ '/fun/' | relative_url }}) |
| Chat charts | `!ccdeny` / `!ccallow <#channel>` keeps channels out of `!chatchart` | |
| Bot nickname, server prefix | `!set bot nickname`, `!set serverprefix` | |

## Slash commands

Some features have slash versions: `/games …`, `/catchup`, `/translate`. The bot owner turns them on with `!slash enable <name>` and then `!slash sync`.
