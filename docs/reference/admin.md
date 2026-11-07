---
title: Admin
parent: Command reference
nav_order: 2
permalink: /reference/admin/
---

# Admin

A collection of server administration utilities.

For a task-by-task guide, see [Server setup]({{ '/admin/' | relative_url }}).

{% raw %}
<a id="addrole"></a>
### !addrole

`!addrole <rolename> [user=<you>]`

**Who:** admins, or anyone with the manage roles permission

Add a role to a user.

Use double quotes if the role contains spaces.
If user is left blank it defaults to the author of the command.

<a id="announceset"></a>
### !announceset

`!announceset`

**Who:** server owners, or anyone with the administrator permission

Change how announcements are sent in this guild.

<a id="announceset-channel"></a>
### !announceset channel

`!announceset channel <channel>`

**Who:** server owners, or anyone with the administrator permission

Change the channel where the bot will send announcements.

<a id="announceset-clearchannel"></a>
### !announceset clearchannel

`!announceset clearchannel`

**Who:** server owners, or anyone with the administrator permission

Unsets the channel for announcements.

<a id="editrole"></a>
### !editrole

`!editrole`

**Who:** admins, or anyone with the manage roles permission

Edit role settings.

<a id="editrole-colour"></a>
### !editrole colour

`!editrole colour <role> <value>`

**Who:** admins, or anyone with the manage roles permission · **Also:** `!editrole color`

Edit a role's colour.

Use double quotes if the role contains spaces.
Colour must be in hexadecimal format.
[Online colour picker](http://www.w3schools.com/colors/colors_picker.asp)

Examples:
    `!editrole colour "The Transistor" #ff0000`
    `!editrole colour Test #ff9900`

<a id="editrole-name"></a>
### !editrole name

`!editrole name <role> <name>`

**Who:** admins, or anyone with the manage roles permission

Edit a role's name.

Use double quotes if the role or the name contain spaces.

Example:
    `!editrole name "The Transistor" Test`

<a id="removerole"></a>
### !removerole

`!removerole <rolename> [user=<you>]`

**Who:** admins, or anyone with the manage roles permission

Remove a role from a user.

Use double quotes if the role contains spaces.
If user is left blank it defaults to the author of the command.

<a id="selfrole"></a>
### !selfrole

`!selfrole <selfrole>`

**Who:** everyone

Add or remove a selfrole from yourself.

Server admins must have configured the role as user settable.
NOTE: The role is case sensitive!

<a id="selfrole-list"></a>
### !selfrole list

`!selfrole list`

**Who:** everyone

Lists all available selfroles.

<a id="selfroleset"></a>
### !selfroleset

`!selfroleset`

**Who:** admins, or anyone with the manage roles permission

Manage selfroles.

<a id="selfroleset-add"></a>
### !selfroleset add

`!selfroleset add <roles...>`

**Who:** admins, or anyone with the manage roles permission

Add a role, or a selection of roles, to the list of available selfroles.

NOTE: The role is case sensitive!

<a id="selfroleset-clear"></a>
### !selfroleset clear

`!selfroleset clear`

**Who:** admins, or anyone with the manage roles permission

Clear the list of available selfroles for this server.

<a id="selfroleset-remove"></a>
### !selfroleset remove

`!selfroleset remove <roles...>`

**Who:** admins, or anyone with the manage roles permission

Remove a role, or a selection of roles, from the list of available selfroles.

NOTE: The role is case sensitive!

{% endraw %}
