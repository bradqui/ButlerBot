---
title: Server setup
nav_order: 22
permalink: /admin/
---

# Server setup
{: .no_toc }

For admins: who can use what, custom commands, the welcome flow, and where each feature's settings live.

1. TOC
{:toc}

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
