---
title: Moderation
nav_order: 20
permalink: /moderation/
---

# Moderation
{: .no_toc }

For mods and admins. Each command lists who can use it: "Mod or Manage Messages" means the bot's mod role, **or** that Discord permission. The server owner sets the mod and admin roles with `!set roles addmodrole <role>` and `!set roles addadminrole <role>`.

{: .note }
> Kicking and banning need the **admin** role or the actual **Kick/Ban Members** permission. The mod role alone isn't enough.

1. TOC
{:toc}

## Warnings

Warnings carry points, and admins can set automatic actions at point thresholds.

| Command | Who |
|---|---|
| `!warn <member> [points] <reason>` | Admin or Ban Members |
| `!warnings <member>` | Admin role |
| `!unwarn <member> <warn id> [reason]` | Admin or Ban Members |
| `!mywarnings` | Everyone (their own) |
| `!reasonlist` / `!actionlist` | Admin or Ban Members |

**Reasons:** by default `<reason>` must be a registered reason name. Turn on free text with `!warningset allowcustomreasons true`.

**Setup** (server owner or Administrator):
- `!warnreason create <name> <points> <description>` registers a reason.
- `!warnaction add <name> <points>` asks for commands to run at that many points, like `mute {user} 1 day`.
- `!warningset senddm`, `showmoderator` and `warnchannel` control how warnings are delivered.

## Muting

| Command | What it does | Who |
|---|---|---|
| `!mute <members> [time and reason]` | Server-wide mute, e.g. `!mute @x spamming 2 hours` | Mod, or Manage Roles + Timeout Members |
| `!unmute <members> [reason]` | | Mod or Manage Roles |
| `!timeout <members> <time> [reason]` | Discord's built-in timeout (28 days max). Creates no modlog case. | Mod or Timeout Members |
| `!mutechannel <members> [time and reason]` | Mute in this channel only | Mod or Manage Roles |
| `!voicemute <members> [time and reason]` | Mute in their current voice channel | Mute Members + Manage Permissions |
| `!activemutes` | List current mutes | Mod or Manage Roles |

**Without a mute role,** `!mute` uses Discord timeouts, which need a duration. Admins can set a role up:
- `!muteset makerole Muted` creates one.
- `!muteset role @Muted` uses an existing one.
- `!muteset defaulttime 1h` sets the length used when none is given.

## Kicks and bans

| Command | What it does | Who |
|---|---|---|
| `!kick <member> [reason]` | | Admin or Kick Members |
| `!ban <user> [days] [reason]` | `days` (0–7) deletes that many days of their messages. Works with IDs of people who already left. | Admin or Ban Members |
| `!tempban <member> [duration] [days] [reason]` | e.g. `!tempban @x 3d being rude`. Defaults to 1 day. | Admin or Ban Members |
| `!softban <member> [reason]` | Kick plus a 1-day message cleanup | Admin or Ban Members |
| `!massban <ids…> [days] [reason]` | Ban many IDs at once | Admin or Ban Members |
| `!unban <user id> [reason]` | | Admin or Ban Members |
| `!voicekick <member>` | Disconnect from voice | Mod or Move Members |
| `!voiceban` / `!voiceunban <member>` | Server-mute and deafen in all voice | Admin or Mute + Deafen Members |

## Cleaning up messages

All need Mod or Manage Messages. Discord can't bulk-delete messages older than 14 days, and deleting more than 100 asks for confirmation. Pinned messages are kept unless you add `True` at the end.

| Command | Deletes |
|---|---|
| `!cleanup messages <n>` | The last n messages |
| `!cleanup user <member> <n>` | The last n from one person |
| `!cleanup text "<text>" <n>` | The last n containing some text |
| `!cleanup after <message id>` | Everything after a message (or reply to it) |
| `!cleanup before <message id> <n>` | n messages before a message |
| `!cleanup between <id1> <id2>` | Everything between two messages |
| `!cleanup bot <n>` | Commands and the bot's replies |
| `!cleanup duplicates [n]` | Repeated messages |

`!clearchannel` (server owner only) wipes **an entire channel**. It works by cloning the channel and deleting the original, so pins, threads and links to old messages are lost.

## Other tools

| Command | What it does | Who |
|---|---|---|
| `!slowmode [interval]` | e.g. `!slowmode 10s`; blank turns it off | Admin or Manage Channel |
| `!rename <member> [nickname]` | Set or clear a nickname | Admin or Manage Nicknames |
| `!userinfo [member]` / `!names <member>` | Join dates, roles, previous names | Everyone |
| `!case <n>` / `!casesfor <member>` / `!listcases <member>` | Look up modlog cases | Everyone |
| `!reason [case] <reason>` | Add or fix a case's reason | The case's moderator or a mod |
| `!forceclass <member> <label>` / `!forcerulesremove <member>` | Fix someone's welcome-flow role, or make them redo the rules | Roles set with `!bg addmodrole` |

## Mod log

Mod actions are recorded as numbered **cases**. To post them in a channel (server owner or Administrator):

```
!modlogset modlog #mod-log
!modlogset cases            shows which case types are on
!modlogset cases kick       toggles one
```

`!timeout` doesn't create cases. Filter hits are off by default.

## Automod

The Mod cog can act on spam automatically (server owner or Administrator):
- `!modset mentionspam ban 8` bans people who mention 8+ users in one message. `warn` and `kick` also work.
- `!modset deleterepeats 3` deletes a message repeated 3 times in a row.
- Other settings: `!modset requirereason`, `defaultdays`, `defaultduration` and `dm sendmessage`.

Mods, admins and anyone on `!autoimmune add <user or role>` are skipped.

See also [Filters and spam]({{ '/filters/' | relative_url }}).
