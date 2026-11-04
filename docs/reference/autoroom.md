---
title: AutoRoom
parent: Command reference
nav_order: 6
permalink: /reference/autoroom/
---

# AutoRoom

Automatic voice channel management.

This cog facilitates automatic voice channel creation.
When a member joins an AutoRoom Source (voice channel),
this cog will move them to a brand new AutoRoom that they have control over.
Once everyone leaves the AutoRoom, it is automatically deleted.

For a quick rundown on how to get started with this cog,
check out [the readme](https://github.com/PhasecoreX/PCXCogs/tree/master/autoroom/README.md)

For a task-by-task guide, see [Voice rooms]({{ '/voice/' | relative_url }}).

{% raw %}
<a id="autoroom"></a>
### !autoroom

`!autoroom`

**Who:** everyone · **Also:** `!vc`

Manage your AutoRoom.

For a quick rundown on how to manage your AutoRoom,
check out [the readme](https://github.com/PhasecoreX/PCXCogs/tree/master/autoroom/README.md)

<a id="autoroom-allow"></a>
### !autoroom allow

`!autoroom allow <member_or_role>`

**Who:** everyone · **Also:** `!autoroom add`

Allow a user (or role) into your AutoRoom.

<a id="autoroom-bitrate"></a>
### !autoroom bitrate

`!autoroom bitrate <kbps>`

**Who:** everyone · **Also:** `!autoroom kbps`

Change the bitrate of your AutoRoom.

<a id="autoroom-claim"></a>
### !autoroom claim

`!autoroom claim`

**Who:** everyone

Claim ownership of this AutoRoom.

<a id="autoroom-deny"></a>
### !autoroom deny

`!autoroom deny <member_or_role>`

**Who:** everyone · **Also:** `!autoroom ban`, `!autoroom block`

Deny a user (or role) from accessing your AutoRoom.

If the user is already in your AutoRoom, they will be disconnected.

If a user is no longer able to access the room due to denying a role,
they too will be disconnected. Keep in mind that if the server is using
member roles, denying roles will probably not work as expected.

<a id="autoroom-locked"></a>
### !autoroom locked

`!autoroom locked`

**Who:** everyone

Lock your AutoRoom (visible, but no one can join).

<a id="autoroom-name"></a>
### !autoroom name

`!autoroom name <name>`

**Who:** everyone

Change the name of your AutoRoom.

<a id="autoroom-private"></a>
### !autoroom private

`!autoroom private`

**Who:** everyone

Make your AutoRoom private.

<a id="autoroom-public"></a>
### !autoroom public

`!autoroom public`

**Who:** everyone

Make your AutoRoom public.

<a id="autoroom-settings"></a>
### !autoroom settings

`!autoroom settings`

**Who:** everyone · **Also:** `!autoroom about`, `!autoroom info`

Display current settings.

<a id="autoroom-users"></a>
### !autoroom users

`!autoroom users <user_limit>`

**Who:** everyone · **Also:** `!autoroom userlimit`

Change the user limit of your AutoRoom.

<a id="autoroomset"></a>
### !autoroomset

`!autoroomset`

**Who:** admins, or anyone with the manage guild permission

Configure the AutoRoom cog.

For a quick rundown on how to get started with this cog,
check out [the readme](https://github.com/PhasecoreX/PCXCogs/tree/master/autoroom/README.md)

<a id="autoroomset-access"></a>
### !autoroomset access

`!autoroomset access`

**Who:** admins, or anyone with the manage guild permission

Control access to all AutoRooms.

Roles that are considered "admin" or "moderator" are
set up with the commands `!set addadminrole`
and `!set addmodrole` (plus the remove commands too)

<a id="autoroomset-access-admin"></a>
### !autoroomset access admin

`!autoroomset access admin`

**Who:** admins, or anyone with the manage guild permission

Allow Admins to join locked/private AutoRooms.

<a id="autoroomset-access-bot"></a>
### !autoroomset access bot

`!autoroomset access bot`

**Who:** admins, or anyone with the manage guild permission

Automatically allow bots into AutoRooms.

The AutoRoom Owner is able to freely allow or deny these roles as they see fit.

<a id="autoroomset-access-bot-add"></a>
### !autoroomset access bot add

`!autoroomset access bot add <role>`

**Who:** admins, or anyone with the manage guild permission

Allow a bot role into every AutoRoom.

<a id="autoroomset-access-bot-remove"></a>
### !autoroomset access bot remove

`!autoroomset access bot remove <role>`

**Who:** admins, or anyone with the manage guild permission · **Also:** `!autoroomset access bot delete`, `!autoroomset access bot del`

Disallow a bot role from joining every AutoRoom.

<a id="autoroomset-access-mod"></a>
### !autoroomset access mod

`!autoroomset access mod`

**Who:** admins, or anyone with the manage guild permission

Allow Moderators to join locked/private AutoRooms.

<a id="autoroomset-create"></a>
### !autoroomset create

`!autoroomset create <source_voice_channel> <dest_category>`

**Who:** admins, or anyone with the manage guild permission · **Also:** `!autoroomset enable`, `!autoroomset add`

Create an AutoRoom Source.

Anyone joining an AutoRoom Source will automatically have a new
voice channel (AutoRoom) created in the destination category,
and then be moved into it.

<a id="autoroomset-modify"></a>
### !autoroomset modify

`!autoroomset modify`

**Who:** admins, or anyone with the manage guild permission · **Also:** `!autoroomset edit`

Modify an existing AutoRoom Source.

<a id="autoroomset-modify-category"></a>
### !autoroomset modify category

`!autoroomset modify category <autoroom_source> <dest_category>`

**Who:** admins, or anyone with the manage guild permission

Set the category that AutoRooms will be created in.

<a id="autoroomset-modify-defaults"></a>
### !autoroomset modify defaults

`!autoroomset modify defaults`

**Who:** admins, or anyone with the manage guild permission · **Also:** `!autoroomset modify bitrate`, `!autoroomset modify memberrole`, `!autoroomset modify other`, `!autoroomset modify perms`, `!autoroomset modify users`

Learn how AutoRoom defaults are set.

<a id="autoroomset-modify-legacytextchannel"></a>
### !autoroomset modify legacytextchannel

`!autoroomset modify legacytextchannel`

**Who:** admins, or anyone with the manage guild permission

Manage if a legacy text channel should be created as well.

<a id="autoroomset-modify-legacytextchannel-disable"></a>
### !autoroomset modify legacytextchannel disable

`!autoroomset modify legacytextchannel disable <autoroom_source>`

**Who:** admins, or anyone with the manage guild permission

Disable creating a legacy text channel with the AutoRoom.

<a id="autoroomset-modify-legacytextchannel-enable"></a>
### !autoroomset modify legacytextchannel enable

`!autoroomset modify legacytextchannel enable <autoroom_source>`

**Who:** admins, or anyone with the manage guild permission

Enable creating a legacy text channel with the AutoRoom.

<a id="autoroomset-modify-legacytextchannel-topic"></a>
### !autoroomset modify legacytextchannel topic

`!autoroomset modify legacytextchannel topic`

**Who:** admins, or anyone with the manage guild permission

Manage the legacy text channel topic.

<a id="autoroomset-modify-legacytextchannel-topic-disable"></a>
### !autoroomset modify legacytextchannel topic disable

`!autoroomset modify legacytextchannel topic disable <autoroom_source>`

**Who:** admins, or anyone with the manage guild permission

Disable setting a legacy text channel topic.

<a id="autoroomset-modify-legacytextchannel-topic-set"></a>
### !autoroomset modify legacytextchannel topic set

`!autoroomset modify legacytextchannel topic set <autoroom_source> <topic_text>`

**Who:** admins, or anyone with the manage guild permission

Set the legacy text channel topic.

- Example:
`This channel is only visible to members of your voice channel, and admins of this server. It will be deleted when everyone leaves. `

<a id="autoroomset-modify-name"></a>
### !autoroomset modify name

`!autoroomset modify name`

**Who:** admins, or anyone with the manage guild permission

Set the default name format of an AutoRoom.

<a id="autoroomset-modify-name-custom"></a>
### !autoroomset modify name custom

`!autoroomset modify name custom <autoroom_source> <template>`

**Who:** admins, or anyone with the manage guild permission

A custom channel name.

Use `{{ expressions }}` to print variables and `{% statements %}` to do basic evaluations on variables.

Variables supported:
- `username` - AutoRoom Owner's username
- `game    ` - AutoRoom Owner's game
- `dupenum ` - An incrementing number that starts at 1, useful for un-duplicating channel names

Statements supported:
- `if/elif/else/endif`
- Example: `{% if dupenum > 1 %}DupeNum is {{dupenum}}, which is greater than 1{% endif %}`
- Another example: `{% if not game %}User isn't playing a game!{% endif %}`

It's kinda like Jinja2, but way simpler. Check out [the readme](https://github.com/PhasecoreX/PCXCogs/tree/master/autoroom/README.md) for more info.

<a id="autoroomset-modify-name-game"></a>
### !autoroomset modify name game

`!autoroomset modify name game <autoroom_source>`

**Who:** admins, or anyone with the manage guild permission

The users current playing game, otherwise the username format.

Custom format example:
`{{game}}{% if not game %}{{username}}'s Room{% endif %}{% if dupenum > 1 %} ({{dupenum}}){% endif %}`

<a id="autoroomset-modify-name-username"></a>
### !autoroomset modify name username

`!autoroomset modify name username <autoroom_source>`

**Who:** admins, or anyone with the manage guild permission

Default format: PhasecoreX's Room.

Custom format example:
`{{username}}'s Room{% if dupenum > 1 %} ({{dupenum}}){% endif %}`

<a id="autoroomset-modify-specialperms"></a>
### !autoroomset modify specialperms

`!autoroomset modify specialperms`

**Who:** admins, or anyone with the manage guild permission

Modify special AutoRoom permissions.

Remember, most permissions are automatically copied
from the AuthRoom Source over to the AutoRoom.
These are for configuring special cases.

<a id="autoroomset-modify-specialperms-ownermodify"></a>
### !autoroomset modify specialperms ownermodify

`!autoroomset modify specialperms ownermodify <autoroom_source>`

**Who:** admins, or anyone with the manage guild permission

Allow AutoRoom Owners to have the Manage Channels permission on their AutoRoom.

<a id="autoroomset-modify-specialperms-sendmessage"></a>
### !autoroomset modify specialperms sendmessage

`!autoroomset modify specialperms sendmessage <autoroom_source>`

**Who:** admins, or anyone with the manage guild permission

Allow users to send messages in the AutoRoom built in text channel.

<a id="autoroomset-modify-text"></a>
### !autoroomset modify text

`!autoroomset modify text`

**Who:** admins, or anyone with the manage guild permission

Configure sending an introductory message to the AutoRoom text channel.

<a id="autoroomset-modify-text-disable"></a>
### !autoroomset modify text disable

`!autoroomset modify text disable <autoroom_source>`

**Who:** admins, or anyone with the manage guild permission

Disable sending a message to the newly generated AutoRoom text channel.

<a id="autoroomset-modify-text-set"></a>
### !autoroomset modify text set

`!autoroomset modify text set <autoroom_source> <hint_text>`

**Who:** admins, or anyone with the manage guild permission

Send a message to the newly generated AutoRoom text channel.

This can have template variables and statements, which you can learn more
about by looking at `!autoroomset modify name custom`, or by looking at
[the readme](https://github.com/PhasecoreX/PCXCogs/tree/master/autoroom/README.md).

The only additional variable that may be useful here is the `mention` variable,
which will insert the users mention (pinging them).

- Example:
`Hello {{mention}}! Welcome to your new AutoRoom!`

<a id="autoroomset-modify-type"></a>
### !autoroomset modify type

`!autoroomset modify type`

**Who:** admins, or anyone with the manage guild permission

Choose what type of AutoRoom is created.

<a id="autoroomset-modify-type-locked"></a>
### !autoroomset modify type locked

`!autoroomset modify type locked <autoroom_source>`

**Who:** admins, or anyone with the manage guild permission

Rooms will be visible to all, but not joinable. AutoRoom Owner can allow users in.

<a id="autoroomset-modify-type-private"></a>
### !autoroomset modify type private

`!autoroomset modify type private <autoroom_source>`

**Who:** admins, or anyone with the manage guild permission

Rooms will be hidden. AutoRoom Owner can allow users in.

<a id="autoroomset-modify-type-public"></a>
### !autoroomset modify type public

`!autoroomset modify type public <autoroom_source>`

**Who:** admins, or anyone with the manage guild permission

Rooms will be open to all. AutoRoom Owner has control over room.

<a id="autoroomset-modify-type-server"></a>
### !autoroomset modify type server

`!autoroomset modify type server <autoroom_source>`

**Who:** admins, or anyone with the manage guild permission

Rooms will be open to all, but the server owns the AutoRoom (so they can't be modified).

<a id="autoroomset-permissions"></a>
### !autoroomset permissions

`!autoroomset permissions`

**Who:** admins, or anyone with the manage guild permission · **Also:** `!autoroomset perms`

Check that the bot has all needed permissions.

<a id="autoroomset-remove"></a>
### !autoroomset remove

`!autoroomset remove <autoroom_source>`

**Who:** admins, or anyone with the manage guild permission · **Also:** `!autoroomset disable`, `!autoroomset delete`, `!autoroomset del`

Remove an AutoRoom Source.

<a id="autoroomset-settings"></a>
### !autoroomset settings

`!autoroomset settings`

**Who:** admins, or anyone with the manage guild permission

Display current settings.

{% endraw %}
