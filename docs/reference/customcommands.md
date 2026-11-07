---
title: CustomCommands
parent: Command reference
nav_order: 13
permalink: /reference/customcommands/
---

# CustomCommands

This cog contains commands for creating and managing custom commands that display text.

These are useful for storing information members might need, like FAQ answers or invite links.
Custom commands can be used by anyone by default, so be careful with pings.
Commands can only be lowercase, and will not respond to any uppercase letters.

For a task-by-task guide, see [Server setup]({{ '/admin/' | relative_url }}).

{% raw %}
<a id="customcom"></a>
### !customcom

`!customcom`

**Who:** everyone · **Also:** `!cc`

Base command for Custom Commands management.

<a id="customcom-cooldown"></a>
### !customcom cooldown

`!customcom cooldown <command> [cooldown] [per=member]`

**Who:** mods, or anyone with the administrator permission

Set, edit, or view the cooldown for a custom command.

You may set cooldowns per member, channel, or guild. Multiple
cooldowns may be set. All cooldowns must be cooled to call the
custom command.

Examples:
- `!customcom cooldown pingrole`
- `!customcom cooldown yourcommand 30`
- `!cc cooldown mycommand 30 guild`

**Arguments:**

- `<command>` The custom command to check or set the cooldown.
- `[cooldown]` The number of seconds to wait before allowing the command to be invoked again. If omitted, will instead return the current cooldown settings.
- `[per]` The group to apply the cooldown on. Defaults to per member. Valid choices are server / guild, user / member, and channel.

<a id="customcom-create"></a>
### !customcom create

`!customcom create <command> <text>`

**Who:** mods, or anyone with the administrator permission · **Also:** `!customcom add`

Create custom commands.

If a type is not specified, a simple CC will be created.
CCs can be enhanced with arguments, see the guide
[here](https://docs.discord.red/en/stable/cog_customcom.html).

<a id="customcom-create-random"></a>
### !customcom create random

`!customcom create random <command>`

**Who:** mods, or anyone with the administrator permission

Create a CC where it will randomly choose a response!

Note: This command is interactive.

**Arguments:**

- `<command>` The command executed to return the text. Cast to lowercase.

<a id="customcom-create-simple"></a>
### !customcom create simple

`!customcom create simple <command> <text>`

**Who:** mods, or anyone with the administrator permission

Add a simple custom command.

Example:
- `!customcom create simple yourcommand Text you want`

**Arguments:**

- `<command>` The command executed to return the text. Cast to lowercase.
- `<text>` The text to return when executing the command. See guide for enhanced usage.

<a id="customcom-delete"></a>
### !customcom delete

`!customcom delete <command>`

**Who:** mods, or anyone with the administrator permission · **Also:** `!customcom del`, `!customcom remove`

Delete a custom command.

Example:
- `!customcom delete yourcommand`

**Arguments:**

- `<command>` The custom command to delete.

<a id="customcom-edit"></a>
### !customcom edit

`!customcom edit <command> [text]`

**Who:** mods, or anyone with the administrator permission

Edit a custom command.

Example:
- `!customcom edit yourcommand Text you want`

**Arguments:**

- `<command>` The custom command to edit.
- `<text>` The new text to return when executing the command.

<a id="customcom-list"></a>
### !customcom list

`!customcom list`

**Who:** everyone

List all available custom commands.

The list displays a preview of each command's response, with
markdown escaped and newlines replaced with spaces.

<a id="customcom-raw"></a>
### !customcom raw

`!customcom raw <command>`

**Who:** everyone

Get the raw response of a custom command, to get the proper markdown.

This is helpful for copy and pasting.

**Arguments:**

- `<command>` The custom command to get the raw response of.

<a id="customcom-search"></a>
### !customcom search

`!customcom search <query>`

**Who:** everyone

Searches through custom commands, according to the query.

Uses fuzzy searching to find close matches.

**Arguments:**

- `<query>` The query to search for. Can be multiple words.

<a id="customcom-show"></a>
### !customcom show

`!customcom show <command_name>`

**Who:** everyone

Shows a custom command's responses and its settings.

**Arguments:**

- `<command_name>` The custom command to show.

{% endraw %}
