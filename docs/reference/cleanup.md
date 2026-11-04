---
title: Cleanup
parent: Command reference
nav_order: 12
permalink: /reference/cleanup/
---

# Cleanup

This cog contains commands used for "cleaning up" (deleting) messages.

This is designed as a moderator tool and offers many convenient use cases.
All cleanup commands only apply to the channel the command is executed in.

Messages older than two weeks cannot be mass deleted.
This is a limitation of the API.

For a task-by-task guide, see [Moderation]({{ '/moderation/' | relative_url }}).

{% raw %}
<a id="cleanup"></a>
### !cleanup

`!cleanup`

**Who:** everyone

Base command for deleting messages.

<a id="cleanup-after"></a>
### !cleanup after

`!cleanup after [message_id] [delete_pinned=False]`

**Who:** mods, or anyone with the manage messages permission

Delete all messages after a specified message.

To get a message id, enable developer mode in Discord's
settings, 'appearance' tab. Then right click a message
and copy its id.
Replying to a message will cleanup all messages after it.

**Arguments:**

- `<message_id>` The id of the message to cleanup after. This message won't be deleted.
- `<delete_pinned>` Whether to delete pinned messages or not. Defaults to False

<a id="cleanup-before"></a>
### !cleanup before

`!cleanup before [message_id] <number> [delete_pinned=False]`

**Who:** mods, or anyone with the manage messages permission

Deletes X messages before the specified message.

To get a message id, enable developer mode in Discord's
settings, 'appearance' tab. Then right click a message
and copy its id.
Replying to a message will cleanup all messages before it.

**Arguments:**

- `<message_id>` The id of the message to cleanup before. This message won't be deleted.
- `<number>` The max number of messages to cleanup. Must be a positive integer.
- `<delete_pinned>` Whether to delete pinned messages or not. Defaults to False

<a id="cleanup-between"></a>
### !cleanup between

`!cleanup between <one> <two> [delete_pinned=False]`

**Who:** mods, or anyone with the manage messages permission

Delete the messages between Message One and Message Two, providing the messages IDs.

The first message ID should be the older message and the second one the newer.

Example:
- `!cleanup between 123456789123456789 987654321987654321`

**Arguments:**

- `<one>` The id of the message to cleanup after. This message won't be deleted.
- `<two>` The id of the message to cleanup before. This message won't be deleted.
- `<delete_pinned>` Whether to delete pinned messages or not. Defaults to False

<a id="cleanup-bot"></a>
### !cleanup bot

`!cleanup bot <number> [delete_pinned=False]`

**Who:** mods, or anyone with the manage messages permission

Clean up command messages and messages from the bot in the current channel.

Can only cleanup custom commands and alias commands if those cogs are loaded.

**Arguments:**

- `<number>` The max number of messages to cleanup. Must be a positive integer.
- `<delete_pinned>` Whether to delete pinned messages or not. Defaults to False

<a id="cleanup-duplicates"></a>
### !cleanup duplicates

`!cleanup duplicates [number=50]`

**Who:** mods, or anyone with the manage messages permission · **Also:** `!cleanup spam`

Deletes duplicate messages in the channel from the last X messages and keeps only one copy.

Defaults to 50.

**Arguments:**

- `<number>` The number of messages to check for duplicates. Must be a positive integer.

<a id="cleanup-messages"></a>
### !cleanup messages

`!cleanup messages <number> [delete_pinned=False]`

**Who:** mods, or anyone with the manage messages permission

Delete the last X messages in the current channel.

Example:
- `!cleanup messages 26`

**Arguments:**

- `<number>` The max number of messages to cleanup. Must be a positive integer.
- `<delete_pinned>` Whether to delete pinned messages or not. Defaults to False

<a id="cleanup-self"></a>
### !cleanup self

`!cleanup self <number> [match_pattern] [delete_pinned=False]`

**Who:** everyone

Clean up messages owned by the bot in the current channel.

By default, all messages are cleaned. If a second argument is specified,
it is used for pattern matching - only messages containing the given text will be deleted.

Examples:
- `!cleanup self 6`
- `!cleanup self 10 Pong`
- `!cleanup self 7 "" True`

**Arguments:**

- `<number>` The max number of messages to cleanup. Must be a positive integer.
- `<match_pattern>` The text that messages must contain to be deleted. Use "" to skip this.
- `<delete_pinned>` Whether to delete pinned messages or not. Defaults to False

<a id="cleanup-text"></a>
### !cleanup text

`!cleanup text <text> <number> [delete_pinned=False]`

**Who:** mods, or anyone with the manage messages permission

Delete the last X messages matching the specified text in the current channel.

Example:
- `!cleanup text "test" 5`

Remember to use double quotes.

**Arguments:**

- `<number>` The max number of messages to cleanup. Must be a positive integer.
- `<delete_pinned>` Whether to delete pinned messages or not. Defaults to False

<a id="cleanup-user"></a>
### !cleanup user

`!cleanup user <user> <number> [delete_pinned=False]`

**Who:** mods, or anyone with the manage messages permission

Delete the last X messages from a specified user in the current channel.

Examples:
- `!cleanup user @Twentysix 2`
- `!cleanup user Red 6`

**Arguments:**

- `<user>` The user whose messages are to be cleaned up.
- `<number>` The max number of messages to cleanup. Must be a positive integer.
- `<delete_pinned>` Whether to delete pinned messages or not. Defaults to False

<a id="cleanupset"></a>
### !cleanupset

`!cleanupset`

**Who:** admins, or anyone with the manage messages permission

Manage the settings for the cleanup command.

<a id="cleanupset-notify"></a>
### !cleanupset notify

`!cleanupset notify`

**Who:** admins, or anyone with the manage messages permission

Toggle clean up notification settings.

When enabled, a message will be sent per cleanup, showing how many messages were deleted.
This message will be deleted after 5 seconds.

{% endraw %}
