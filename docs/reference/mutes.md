---
title: Mutes
parent: Command reference
nav_order: 22
permalink: /reference/mutes/
---

# Mutes

Mute users temporarily or indefinitely.

For a task-by-task guide, see [Moderation]({{ '/moderation/' | relative_url }}).

{% raw %}
<a id="activemutes"></a>
### !activemutes

`!activemutes`

**Who:** mods, or anyone with the manage roles permission

Displays active mutes on this server.

<a id="mute"></a>
### !mute

`!mute <users...> [time_and_reason]`

**Who:** mods, or anyone with the manage roles, moderate members permission

Mute users.

`<users...>` is a space separated list of usernames, ID's, or mentions.
`[time_and_reason]` is the time to mute for and reason. Time is
any valid time length such as `30 minutes` or `2 days`. If nothing
is provided the mute will use the set default time or indefinite if not set.

Examples:
`!mute @member1 @member2 spam 5 hours`
`!mute @member1 3 days`

<a id="mutechannel"></a>
### !mutechannel

`!mutechannel <users...> [time_and_reason]`

**Who:** mods, or anyone with the manage roles permission · **Also:** `!channelmute`

Mute a user in the current text channel (or in the parent of the current thread).

`<users...>` is a space separated list of usernames, ID's, or mentions.
`[time_and_reason]` is the time to mute for and reason. Time is
any valid time length such as `30 minutes` or `2 days`. If nothing
is provided the mute will use the set default time or indefinite if not set.

Examples:
`!mutechannel @member1 @member2 spam 5 hours`
`!mutechannel @member1 3 days`

<a id="muteset"></a>
### !muteset

`!muteset`

**Who:** everyone

Mute settings.

<a id="muteset-defaulttime"></a>
### !muteset defaulttime

`!muteset defaulttime [time]`

**Who:** mods, or anyone with the manage messages permission · **Also:** `!muteset time`

Set the default mute time for the mute command.

If no time interval is provided this will be cleared.

<a id="muteset-makerole"></a>
### !muteset makerole

`!muteset makerole <name>`

**Who:** admins, or anyone with the manage roles permission

Create a Muted role.

This will create a role and apply overwrites to all available channels
to more easily setup muting a user.

If you already have a muted role created on the server use
`!muteset role ROLE_NAME_HERE`

<a id="muteset-notification"></a>
### !muteset notification

`!muteset notification [channel]`

**Who:** admins, or anyone with the manage channels permission

Set the notification channel for automatic unmute issues.

If no channel is provided this will be cleared and notifications
about issues when unmuting users will not be sent anywhere.

<a id="muteset-role"></a>
### !muteset role

`!muteset role [role]`

**Who:** admins, or anyone with the manage roles permission

Sets the role to be applied when muting a user.

If no role is setup the bot will attempt to mute a user
by utilizing server timeouts.

Note: If no role is setup a user may be able to leave the server
and rejoin no longer being muted.

<a id="muteset-senddm"></a>
### !muteset senddm

`!muteset senddm <true_or_false>`

**Who:** mods, or anyone with the manage channels permission

Set whether mute notifications should be sent to users in DMs.

<a id="muteset-settings"></a>
### !muteset settings

`!muteset settings`

**Who:** mods, or anyone with the manage channels permission · **Also:** `!muteset showsettings`

Shows the current mute settings for this guild.

<a id="muteset-showmoderator"></a>
### !muteset showmoderator

`!muteset showmoderator <true_or_false>`

**Who:** mods, or anyone with the manage channels permission

Decide whether the name of the moderator muting a user should be included in the DM to that user.

<a id="timeout"></a>
### !timeout

`!timeout <users...> [time_and_reason]`

**Who:** mods, or anyone with the moderate members permission

Timeout users.

`<users...>` is a space separated list of usernames, ID's, or mentions.
`[time_and_reason]` is the time to timeout for and reason. Time is
any valid time length such as `30 minutes` or `2 days`. If nothing
is provided the timeout will use the set default time or give an error if not set.

Examples:
`!timeout @member1 @member2 spam 5 hours`
`!timeout @member1 3 days`

<a id="unmute"></a>
### !unmute

`!unmute <users...> [reason]`

**Who:** mods, or anyone with the manage roles permission

Unmute users.

`<users...>` is a space separated list of usernames, ID's, or mentions.
`[reason]` is the reason for the unmute.

<a id="unmutechannel"></a>
### !unmutechannel

`!unmutechannel <users...> [reason]`

**Who:** mods, or anyone with the manage roles permission · **Also:** `!channelunmute`

Unmute a user in this channel (or in the parent of this thread).

`<users...>` is a space separated list of usernames, ID's, or mentions.
`[reason]` is the reason for the unmute.

<a id="voicemute"></a>
### !voicemute

`!voicemute <users...> [reason]`

**Who:** everyone

Mute a user in their current voice channel.

`<users...>` is a space separated list of usernames, ID's, or mentions.
`[time_and_reason]` is the time to mute for and reason. Time is
any valid time length such as `30 minutes` or `2 days`. If nothing
is provided the mute will use the set default time or indefinite if not set.

Examples:
`!voicemute @member1 @member2 spam 5 hours`
`!voicemute @member1 3 days`

<a id="voiceunmute"></a>
### !voiceunmute

`!voiceunmute <users...> [reason]`

**Who:** everyone

Unmute a user in their current voice channel.

`<users...>` is a space separated list of usernames, ID's, or mentions.
`[reason]` is the reason for the unmute.

{% endraw %}
