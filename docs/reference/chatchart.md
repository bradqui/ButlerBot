---
title: Chatchart
parent: Command reference
nav_order: 8
permalink: /reference/chatchart/
---

# Chatchart

Show activity.

For a task-by-task guide, see [Server stats]({{ '/stats/' | relative_url }}).

{% raw %}
<a id="ccallow"></a>
### !ccallow

`!ccallow <channel>`

**Who:** mods, or anyone with the manage channels permission

Remove a channel from the deny list to allow chatchart use.

<a id="ccdeny"></a>
### !ccdeny

`!ccdeny <channel>`

**Who:** mods, or anyone with the manage channels permission

Add a channel to deny chatchart use.

<a id="ccdenylist"></a>
### !ccdenylist

`!ccdenylist`

**Who:** mods, or anyone with the manage channels permission

List the channels that are denied.

<a id="chatchart"></a>
### !chatchart

`!chatchart [channel] [messages=5000]`

**Who:** everyone

Generates a pie chart, representing the last 5000 messages in the specified channel.

<a id="serverchart"></a>
### !serverchart

`!serverchart [messages=1000]`

**Who:** mods, or anyone with the manage guild permission · **Also:** `!guildchart`

Generates a pie chart, representing the last 1000 messages from every allowed channel in the server.

As example:
For each channel that the bot is allowed to scan. It will take the last 1000 messages from each channel.
And proceed to build a chart out of that.

{% endraw %}
