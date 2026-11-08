---
title: Mod
parent: Command reference
nav_order: 20
permalink: /reference/mod/
---

# Mod

Moderation tools.

For a task-by-task guide, see [Moderation]({{ '/moderation/' | relative_url }}).

{% raw %}
<a id="ban"></a>
### !ban

`!ban <user> [days] [reason]`

**Who:** admins, or anyone with the ban members permission

Ban a user from this server and optionally delete days of messages.

`days` is the amount of days of messages to cleanup on ban.

Examples:
- `!ban 428675506947227648 7 Continued to spam after told to stop.`
    This will ban the user with ID 428675506947227648 and it will delete 7 days worth of messages.
- `!ban @Twentysix 7 Continued to spam after told to stop.`
    This will ban Twentysix and it will delete 7 days worth of messages.

A user ID should be provided if the user is not a member of this server.
If days is not a number, it's treated as the first word of the reason.
Minimum 0 days, maximum 7. If not specified, the defaultdays setting will be used instead.

<a id="kick"></a>
### !kick

`!kick <member> [reason]`

**Who:** admins, or anyone with the kick members permission

Kick a user.

Examples:
- `!kick 428675506947227648 wanted to be kicked.`
    This will kick the user with ID 428675506947227648 from the server.
- `!kick @Twentysix wanted to be kicked.`
    This will kick Twentysix from the server.

If a reason is specified, it will be the reason that shows up
in the audit log.

<a id="massban"></a>
### !massban

`!massban <user_ids...> [days] [reason]`

**Who:** admins, or anyone with the ban members permission · **Also:** `!hackban`

Mass bans user(s) from the server.

`days` is the amount of days of messages to cleanup on massban.

Example:
   - `!massban 345628097929936898 57287406247743488 7 they broke all rules.`
    This will ban all the added userids and delete 7 days worth of their messages.

User IDs need to be provided in order to ban
using this command.

<a id="modset"></a>
### !modset

`!modset`

**Who:** server owners, or anyone with the administrator permission

Manage server administration settings.

<a id="modset-defaultdays"></a>
### !modset defaultdays

`!modset defaultdays [days=0]`

**Who:** server owners, or anyone with the administrator permission

Set the default number of days worth of messages to be deleted when a user is banned.

The number of days must be between 0 and 7.

<a id="modset-defaultduration"></a>
### !modset defaultduration

`!modset defaultduration <duration>`

**Who:** server owners, or anyone with the administrator permission

Set the default time to be used when a user is tempbanned.

Accepts: seconds, minutes, hours, days, weeks
`duration` must be greater than zero.

Examples:
    `!modset defaultduration 7d12h10m`
    `!modset defaultduration 7 days 12 hours 10 minutes`

<a id="modset-deleterepeats"></a>
### !modset deleterepeats

`!modset deleterepeats [repeats]`

**Who:** server owners, or anyone with the administrator permission

Enable auto-deletion of repeated messages.

Must be between 2 and 20.

Set to -1 to disable this feature.

<a id="modset-dm"></a>
### !modset dm

`!modset dm`

**Who:** server owners, or anyone with the administrator permission

Settings for messaging the user when being kicked or banned.

<a id="modset-dm-banextrafieldcontents"></a>
### !modset dm banextrafieldcontents

`!modset dm banextrafieldcontents <contents>`

**Who:** server owners, or anyone with the administrator permission

Set the contents for the optional extra embed on ban

Cannot be over 1024 characters long.

<a id="modset-dm-banextrafieldtitle"></a>
### !modset dm banextrafieldtitle

`!modset dm banextrafieldtitle <title>`

**Who:** server owners, or anyone with the administrator permission

Set the title for the optional extra embed on ban.

Cannot be over 252 characters long.

<a id="modset-dm-banshowextrafield"></a>
### !modset dm banshowextrafield

`!modset dm banshowextrafield [enabled]`

**Who:** server owners, or anyone with the administrator permission

Toggle whether to show an extra customizable field when banning.

This can be used to add additional information for the banned user, such as a ban appeal link.

<a id="modset-dm-sendmessage"></a>
### !modset dm sendmessage

`!modset dm sendmessage [enabled]`

**Who:** server owners, or anyone with the administrator permission

Toggle whether a message should be sent to a user when they are kicked/banned.

If this option is enabled, the bot will attempt to DM the user with the guild name
and reason as to why they were kicked/banned.

<a id="modset-hierarchy"></a>
### !modset hierarchy

`!modset hierarchy`

**Who:** server owners, or anyone with the administrator permission

Toggle role hierarchy check for mods and admins.

**WARNING**: Disabling this setting will allow mods to take
actions on users above them in the role hierarchy!

This is enabled by default.

<a id="modset-mentionspam"></a>
### !modset mentionspam

`!modset mentionspam`

**Who:** server owners, or anyone with the administrator permission

Manage the automoderation settings for mentionspam.

<a id="modset-mentionspam-ban"></a>
### !modset mentionspam ban

`!modset mentionspam ban <max_mentions>`

**Who:** server owners, or anyone with the administrator permission

Set the autoban conditions for mention spam.

Users will be banned if they send any message which contains more than
`<max_mentions>` mentions.

`<max_mentions>` Must be 0 or greater. Set to 0 to disable this feature.

<a id="modset-mentionspam-kick"></a>
### !modset mentionspam kick

`!modset mentionspam kick <max_mentions>`

**Who:** server owners, or anyone with the administrator permission

Sets the autokick conditions for mention spam.

Users will be kicked if they send any messages which contain more than
`<max_mentions>` mentions.

`<max_mentions>` Must be 0 or greater. Set to 0 to disable this feature.

<a id="modset-mentionspam-strict"></a>
### !modset mentionspam strict

`!modset mentionspam strict [enabled]`

**Who:** server owners, or anyone with the administrator permission

Setting to account for duplicate mentions.

If enabled all mentions will count including duplicated mentions.
If disabled only unique mentions will count.

Use this command without any parameter to see current setting.

<a id="modset-mentionspam-warn"></a>
### !modset mentionspam warn

`!modset mentionspam warn <max_mentions>`

**Who:** server owners, or anyone with the administrator permission

Sets the autowarn conditions for mention spam.

Users will be warned if they send any messages which contain more than
`<max_mentions>` mentions.

`<max_mentions>` Must be 0 or greater. Set to 0 to disable this feature.

<a id="modset-reinvite"></a>
### !modset reinvite

`!modset reinvite`

**Who:** server owners, or anyone with the administrator permission

Toggle whether an invite will be sent to a user when unbanned.

If this is True, the bot will attempt to create and send a single-use invite
to the newly-unbanned user.

<a id="modset-requirereason"></a>
### !modset requirereason

`!modset requirereason [enabled]`

**Who:** server owners, or anyone with the administrator permission

Toggle whether a reason is required for mod actions.

If this is enabled, the bot will require a reason to be provided for all mod actions.

<a id="modset-showsettings"></a>
### !modset showsettings

`!modset showsettings`

**Who:** server owners, or anyone with the administrator permission

Show the current server administration settings.

<a id="modset-tracknicknames"></a>
### !modset tracknicknames

`!modset tracknicknames [enabled]`

**Who:** server owners, or anyone with the administrator permission

Toggle whether server nickname changes should be tracked.

This setting will be overridden if trackallnames is disabled.

<a id="names"></a>
### !names

`!names <member>`

**Who:** everyone

Show previous usernames, global display names, and server nicknames of a member.

<a id="rename"></a>
### !rename

`!rename <member> [nickname]`

**Who:** admins, or anyone with the manage nicknames permission

Change a member's server nickname.

Leaving the nickname argument empty will remove it.

<a id="slowmode"></a>
### !slowmode

`!slowmode [interval=0:00:00]`

**Who:** everyone

Changes thread's or text channel's slowmode setting.

Interval can be anything from 0 seconds to 6 hours.
Use without parameters to disable.

<a id="softban"></a>
### !softban

`!softban <member> [reason]`

**Who:** admins, or anyone with the ban members permission

Kick a user and delete 1 day's worth of their messages.

<a id="tempban"></a>
### !tempban

`!tempban <member> [duration] [days] [reason]`

**Who:** admins, or anyone with the ban members permission

Temporarily ban a user from this server.

`duration` is the amount of time the user should be banned for.
`days` is the amount of days of messages to cleanup on tempban.

Examples:
- `!tempban @Twentysix Because I say so`
    This will ban Twentysix for the default amount of time set by an administrator.
- `!tempban @Twentysix 15m You need a timeout`
    This will ban Twentysix for 15 minutes.
- `!tempban 428675506947227648 1d2h15m 5 Evil person`
    This will ban the user with ID 428675506947227648 for 1 day 2 hours 15 minutes and will delete the last 5 days of their messages.

<a id="unban"></a>
### !unban

`!unban <user_id> [reason]`

**Who:** admins, or anyone with the ban members permission

Unban a user from this server.

Requires specifying the target user's ID. To find this, you may either:
1. Copy it from the mod log case (if one was created), or
2. Enable Developer Mode, go to Bans in this server's settings, right-click the user and select 'Copy ID'.

<a id="userinfo"></a>
### !userinfo

`!userinfo [member]`

**Who:** everyone

Show information about a member.

This includes fields for status, discord join date, server
join date, voice state and previous usernames/global display names/nicknames.

If the member has no roles, previous usernames, global display names, or server nicknames,
these fields will be omitted.

<a id="voiceban"></a>
### !voiceban

`!voiceban <member> [reason]`

**Who:** admins, or anyone with the mute members, deafen members permission

Ban a user from speaking and listening in the server's voice channels.

<a id="voicekick"></a>
### !voicekick

`!voicekick <member> [reason]`

**Who:** mods, or anyone with the move members permission

Kick a member from a voice channel.

<a id="voiceunban"></a>
### !voiceunban

`!voiceunban <member> [reason]`

**Who:** admins, or anyone with the mute members, deafen members permission

Unban a user from speaking and listening in the server's voice channels.

{% endraw %}
