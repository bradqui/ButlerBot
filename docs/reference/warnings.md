---
title: Warnings
parent: Command reference
nav_order: 28
permalink: /reference/warnings/
---

# Warnings

Warn misbehaving users and take automated actions.

For a task-by-task guide, see [Moderation]({{ '/moderation/' | relative_url }}).

{% raw %}
<a id="actionlist"></a>
### !actionlist

`!actionlist`

**Who:** admins, or anyone with the ban members permission

List all configured automated actions for Warnings.

<a id="mywarnings"></a>
### !mywarnings

`!mywarnings`

**Who:** everyone

List warnings for yourself.

<a id="reasonlist"></a>
### !reasonlist

`!reasonlist`

**Who:** admins, or anyone with the ban members permission

List all configured reasons for Warnings.

<a id="unwarn"></a>
### !unwarn

`!unwarn <member> <warn_id> [reason]`

**Who:** admins, or anyone with the ban members permission

Remove a warning from a user.

<a id="warn"></a>
### !warn

`!warn <user> [points=1] <reason>`

**Who:** admins, or anyone with the ban members permission

Warn the user for the specified reason.

`<points>` number of points the warning should be for. If no number is supplied
1 point will be given. Pre-set warnings disregard this.
`<reason>` is reason for the warning. This can be a registered reason,
or a custom reason if ``!warningset allowcustomreasons`` is set.

<a id="warnaction"></a>
### !warnaction

`!warnaction`

**Who:** server owners, or anyone with the administrator permission

Manage automated actions for Warnings.

Actions are essentially command macros. Any command can be run
when the action is initially triggered, and/or when the action
is lifted.
Actions must be given a name and a points threshold. When a
user is warned enough so that their points go over this
threshold, the action will be executed.

<a id="warnaction-add"></a>
### !warnaction add

`!warnaction add <name> <points>`

**Who:** server owners, or anyone with the administrator permission

Create an automated action.

Duplicate action names are not allowed.

<a id="warnaction-delete"></a>
### !warnaction delete

`!warnaction delete <action_name>`

**Who:** server owners, or anyone with the administrator permission · **Also:** `!warnaction del`, `!warnaction remove`

Delete the action with the specified name.

<a id="warnings"></a>
### !warnings

`!warnings <member>`

**Who:** admins only

List the warnings for the specified user.

<a id="warningset"></a>
### !warningset

`!warningset`

**Who:** server owners, or anyone with the administrator permission

Manage settings for Warnings.

<a id="warningset-allowcustomreasons"></a>
### !warningset allowcustomreasons

`!warningset allowcustomreasons <allowed>`

**Who:** server owners, or anyone with the administrator permission

Enable or disable custom reasons for a warning.

<a id="warningset-mywarnings"></a>
### !warningset mywarnings

`!warningset mywarnings`

**Who:** server owners, or anyone with the administrator permission

Manage the settings for `!mywarnings`.

<a id="warningset-mywarnings-sendtodms"></a>
### !warningset mywarnings sendtodms

`!warningset mywarnings sendtodms <true_or_false>`

**Who:** server owners, or anyone with the administrator permission

Whether a member self requesting their warnings with `!mywarnings` should get them sent to DMs or in the current channel.

<a id="warningset-senddm"></a>
### !warningset senddm

`!warningset senddm <true_or_false>`

**Who:** server owners, or anyone with the administrator permission

Set whether warnings should be sent to users in DMs.

<a id="warningset-showmoderator"></a>
### !warningset showmoderator

`!warningset showmoderator <true_or_false>`

**Who:** server owners, or anyone with the administrator permission

Decide whether the name of the moderator warning a user should be included in the DM to that user when being
warned or self requesting their warnings.

<a id="warningset-usewarnchannel"></a>
### !warningset usewarnchannel

`!warningset usewarnchannel <true_or_false>`

**Who:** server owners, or anyone with the administrator permission

Set if warnings should be sent to a channel set with `!warningset warnchannel`.

<a id="warningset-warnchannel"></a>
### !warningset warnchannel

`!warningset warnchannel [channel]`

**Who:** server owners, or anyone with the administrator permission

Set the channel where warnings should be sent to.

Leave empty to use the channel `!warn` command was called in.

<a id="warnreason"></a>
### !warnreason

`!warnreason`

**Who:** server owners, or anyone with the administrator permission

Manage warning reasons.

Reasons must be given a name, description and points value. The
name of the reason must be given when a user is warned.

<a id="warnreason-create"></a>
### !warnreason create

`!warnreason create <name> <points> <description>`

**Who:** server owners, or anyone with the administrator permission · **Also:** `!warnreason add`

Create a warning reason.

<a id="warnreason-delete"></a>
### !warnreason delete

`!warnreason delete <reason_name>`

**Who:** server owners, or anyone with the administrator permission · **Also:** `!warnreason remove`, `!warnreason del`

Delete a warning reason.

{% endraw %}
