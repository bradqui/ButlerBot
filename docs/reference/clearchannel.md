---
title: ClearChannel
parent: Command reference
nav_order: 13
permalink: /reference/clearchannel/
---

# ClearChannel

A cog to delete ALL messages of a channel!

⚠ The channel will be cloned, and then **deleted**.

For a task-by-task guide, see [Moderation]({{ '/moderation/' | relative_url }}).

{% raw %}
<a id="clearchannel"></a>
### !clearchannel

`!clearchannel [confirmation=False]`

**Who:** server owners only

Delete ALL messages from the current channel by duplicating it and then deleting it.

For security reasons, only the server owner and the bot owner can use the command. Use the "permissions" cog for more options.
⚠ The channel will be cloned, and then **deleted**.

<a id="setclearchannel"></a>
### !setclearchannel

`!setclearchannel`

**Who:** server owners only · **Also:** `!clearchannelset`

Configure ClearChannel for your server.

<a id="setclearchannel-channeldelete"></a>
### !setclearchannel channeldelete

`!setclearchannel channeldelete <channel_delete>`

**Who:** server owners only

If this option is disabled, the bot will not delete the original channel: it will duplicate it as normal, but move it to the end of the server's channel list.

Default value: `True`
Dev: `<class 'bool'>`

<a id="setclearchannel-custommessage"></a>
### !setclearchannel custommessage

`!setclearchannel custommessage <custom_message>`

**Who:** server owners only

Specify a custom message to be sent from the link of another message or a json (https://discohook.org/ for example).

Use the variables `{user_name}`, `{user_avatar_url}`, `{user_mention}`, `{user_id}`, `{channel_name}`, `{channel_mention}` and `{channel_id}`.

Default value: `...`
Dev: `<class 'AAA3A_utils.settings.CustomMessageConverter'>`

<a id="setclearchannel-dmauthor"></a>
### !setclearchannel dmauthor

`!setclearchannel dmauthor <dm_author>`

**Who:** server owners only

If this option is enabled, the bot will try to send a dm to the author of the order to confirm that everything went well.

Default value: `...`
Dev: `<class 'bool'>`

<a id="setclearchannel-firstmessage"></a>
### !setclearchannel firstmessage

`!setclearchannel firstmessage <first_message>`

**Who:** server owners only

If this option is enabled, the bot will send a message to the emptied channel to inform that it has been emptied.

Default value: `True`
Dev: `<class 'bool'>`

<a id="setclearchannel-modalconfig"></a>
### !setclearchannel modalconfig

`!setclearchannel modalconfig [confirmation=False]`

**Who:** server owners only · **Also:** `!setclearchannel configmodal`

Set all settings for the cog with a Discord Modal.

<a id="setclearchannel-promptmessage"></a>
### !setclearchannel promptmessage

`!setclearchannel promptmessage <prompt_message>`

**Who:** server owners only

Specify a custom message to be sent to confirm the clearing of the channel.

Use the variables `{user_name}`, `{user_avatar_url}`, `{user_mention}`, `{user_id}`, `{channel_name}`, `{channel_mention}` and `{channel_id}`.

Default value: `...`
Dev: `<class 'AAA3A_utils.settings.CustomMessageConverter'>`

<a id="setclearchannel-resetsetting"></a>
### !setclearchannel resetsetting

`!setclearchannel resetsetting <setting>`

**Who:** server owners only

Reset a setting.

<a id="setclearchannel-showsettings"></a>
### !setclearchannel showsettings

`!setclearchannel showsettings [with_dev=False]`

**Who:** server owners only

Show all settings for the cog with defaults and values.

{% endraw %}
