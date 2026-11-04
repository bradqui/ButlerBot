---
title: Alias
parent: Command reference
nav_order: 4
permalink: /reference/alias/
---

# Alias

Create aliases for commands.

Aliases are alternative names/shortcuts for commands. They
can act as both a lambda (storing arguments for repeated use)
or as simply a shortcut to saying "x y z".

When run, aliases will accept any additional arguments
and append them to the stored alias.

For a task-by-task guide, see [Server setup]({{ '/admin/' | relative_url }}).

{% raw %}
<a id="alias"></a>
### !alias

`!alias`

**Who:** everyone

Manage command aliases.

<a id="alias-add"></a>
### !alias add

`!alias add <alias_name> <command>`

**Who:** mods, or anyone with the manage guild permission

Add an alias for a command.

<a id="alias-delete"></a>
### !alias delete

`!alias delete <alias_name>`

**Who:** mods, or anyone with the manage guild permission · **Also:** `!alias del`, `!alias remove`

Delete an existing alias on this server.

<a id="alias-edit"></a>
### !alias edit

`!alias edit <alias_name> <command>`

**Who:** mods, or anyone with the manage guild permission

Edit an existing alias in this server.

<a id="alias-global"></a>
### !alias global

`!alias global`

**Who:** everyone

Manage global aliases.

<a id="alias-global-list"></a>
### !alias global list

`!alias global list`

**Who:** everyone

List the available global aliases on this bot.

<a id="alias-help"></a>
### !alias help

`!alias help <alias_name>`

**Who:** everyone

Try to execute help for the base command of the alias.

<a id="alias-list"></a>
### !alias list

`!alias list`

**Who:** everyone

List the available aliases on this server.

<a id="alias-show"></a>
### !alias show

`!alias show <alias_name>`

**Who:** everyone

Show what command the alias executes.

{% endraw %}
