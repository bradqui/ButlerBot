---
title: ButtonGreeter
parent: Command reference
nav_order: 5
permalink: /reference/buttongreeter/
---

# ButtonGreeter

Welcome buttons for new members: pick a group (role and nickname tag), then agree to the rules.

For a task-by-task guide, see [Server setup]({{ '/admin/' | relative_url }}).

{% raw %}
<a id="buttongreeter"></a>
### !buttongreeter

`!buttongreeter`

**Who:** admins, or anyone with the manage roles permission · **Also:** `!bg`

Admin settings for the welcome flow: channels, group buttons and the rules role.

<a id="buttongreeter-addmodrole"></a>
### !buttongreeter addmodrole

`!buttongreeter addmodrole <role>`

**Who:** admins, or anyone with the manage roles permission

Let a role use `!forceclass` and `!forcerulesremove`.

<a id="buttongreeter-addrole"></a>
### !buttongreeter addrole

`!buttongreeter addrole <role> <button_label>`

**Who:** admins, or anyone with the manage roles permission

Add a group button to the welcome message. Its label becomes the nickname tag.

<a id="buttongreeter-removemodrole"></a>
### !buttongreeter removemodrole

`!buttongreeter removemodrole <role>`

**Who:** admins, or anyone with the manage roles permission

Stop a role from using the force commands.

<a id="buttongreeter-removerole"></a>
### !buttongreeter removerole

`!buttongreeter removerole <button_label>`

**Who:** admins, or anyone with the manage roles permission

Remove a group button.

<a id="buttongreeter-setadminchannel"></a>
### !buttongreeter setadminchannel

`!buttongreeter setadminchannel <channel>`

**Who:** admins, or anyone with the manage roles permission

Set the channel where problems with the welcome flow are reported.

<a id="buttongreeter-setchannel"></a>
### !buttongreeter setchannel

`!buttongreeter setchannel <channel>`

**Who:** admins, or anyone with the manage roles permission

Set the channel where new members are greeted.

<a id="buttongreeter-setruleschannel"></a>
### !buttongreeter setruleschannel

`!buttongreeter setruleschannel <channel>`

**Who:** admins, or anyone with the manage roles permission

Set the channel that has your server rules.

<a id="buttongreeter-setrulesrole"></a>
### !buttongreeter setrulesrole

`!buttongreeter setrulesrole <role>`

**Who:** admins, or anyone with the manage roles permission

Set the role members get when they agree to the rules.

<a id="buttongreeter-settings"></a>
### !buttongreeter settings

`!buttongreeter settings`

**Who:** admins, or anyone with the manage roles permission

Show the current channels, roles and buttons.

<a id="changerole"></a>
### !changerole

`!changerole <exact_label>`

**Who:** everyone

Switch your group if you clicked the wrong button. Use the button's exact label.

<a id="forceclass"></a>
### !forceclass

`!forceclass <member> <exact_label>`

**Who:** everyone

(Admins and welcome mod roles) Put a member in a group: its role and nickname tag.

<a id="forcerulesremove"></a>
### !forcerulesremove

`!forcerulesremove <member>`

**Who:** everyone

(Admins and welcome mod roles) Take the rules role away from a member.

{% endraw %}
