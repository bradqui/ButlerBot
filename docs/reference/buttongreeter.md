---
title: ButtonGreeter
parent: Command reference
nav_order: 8
permalink: /reference/buttongreeter/
---

# ButtonGreeter

A welcome system that greets users with buttons to self-assign a role/nickname, 
followed by a mandatory rules agreement check.

For a task-by-task guide, see [Server setup]({{ '/admin/' | relative_url }}).

{% raw %}
<a id="buttongreeter"></a>
### !buttongreeter

`!buttongreeter`

**Who:** admins, or anyone with the manage roles permission · **Also:** `!bg`

Admin configuration commands for the Welcome/Role system.

<a id="buttongreeter-addmodrole"></a>
### !buttongreeter addmodrole

`!buttongreeter addmodrole <role>`

**Who:** admins, or anyone with the manage roles permission

Authorize a role to use the 'forceclass' and 'forcerulesremove' commands.

<a id="buttongreeter-addrole"></a>
### !buttongreeter addrole

`!buttongreeter addrole <role> <button_label>`

**Who:** admins, or anyone with the manage roles permission

Add a button to the welcome message that assigns a specific role.

<a id="buttongreeter-removemodrole"></a>
### !buttongreeter removemodrole

`!buttongreeter removemodrole <role>`

**Who:** admins, or anyone with the manage roles permission

Remove a role's authorization to use force commands.

<a id="buttongreeter-removerole"></a>
### !buttongreeter removerole

`!buttongreeter removerole <button_label>`

**Who:** admins, or anyone with the manage roles permission

Remove a button from the configuration.

<a id="buttongreeter-setadminchannel"></a>
### !buttongreeter setadminchannel

`!buttongreeter setadminchannel <channel>`

**Who:** admins, or anyone with the manage roles permission

Set the channel where error logs should be sent.

<a id="buttongreeter-setchannel"></a>
### !buttongreeter setchannel

`!buttongreeter setchannel <channel>`

**Who:** admins, or anyone with the manage roles permission

Set the channel where new members are greeted.

<a id="buttongreeter-setruleschannel"></a>
### !buttongreeter setruleschannel

`!buttongreeter setruleschannel <channel>`

**Who:** admins, or anyone with the manage roles permission

Set the channel that contains your server rules.

<a id="buttongreeter-setrulesrole"></a>
### !buttongreeter setrulesrole

`!buttongreeter setrulesrole <role>`

**Who:** admins, or anyone with the manage roles permission

Set the role given to a user when they click 'Yes' to accept rules.

<a id="buttongreeter-settings"></a>
### !buttongreeter settings

`!buttongreeter settings`

**Who:** admins, or anyone with the manage roles permission

Show the current configuration for channels, roles, and buttons.

<a id="changerole"></a>
### !changerole

`!changerole <exact_label>`

**Who:** everyone

Self-service command to change your role if you clicked the wrong button.

<a id="forceclass"></a>
### !forceclass

`!forceclass <member> <exact_label>`

**Who:** everyone

(Authorized Mod Roles Only) Force assign a specific class role to a user.

<a id="forcerulesremove"></a>
### !forcerulesremove

`!forcerulesremove <member>`

**Who:** everyone

(Authorized Mod Roles Only) Remove the 'Rules Agreed' role from a user.

{% endraw %}
