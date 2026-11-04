---
title: GeminiChat
parent: Command reference
nav_order: 22
permalink: /reference/geminichat/
---

# GeminiChat

Image generation with Google Gemini.

Chat is handled by the Claude cog, which hands image requests ("draw ...",
"image of ...") to this cog. You can also use `!draw` directly.

For a task-by-task guide, see [AI chat and images]({{ '/ai/' | relative_url }}).

{% raw %}
<a id="draw"></a>
### !draw

`!draw [prompt]`

**Who:** everyone

Generate an image with Gemini.

Use `!draw edit <changes>` to refine the last image in this channel.
You can also ask in chat: `!ai draw a castle at sunset`.

<a id="draw-edit"></a>
### !draw edit

`!draw edit <changes>`

**Who:** everyone

Refine the last image generated in this channel.

<a id="gemini"></a>
### !gemini

`!gemini`

**Who:** everyone

Gemini image generation settings.

<a id="gemini-channelmodel"></a>
### !gemini channelmodel

`!gemini channelmodel <model_name>`

**Who:** mods, or anyone with the manage channels permission

Set the image model for this channel. Aliases: `image`, `3image`.

<a id="gemini-list"></a>
### !gemini list

`!gemini list`

**Who:** everyone

List the Gemini models that can generate images.

<a id="gemini-model"></a>
### !gemini model

`!gemini model <model_name>`

**Who:** everyone

Set the image model for your private requests. Aliases: `image`, `3image`.

<a id="gemini-settings"></a>
### !gemini settings

`!gemini settings`

**Who:** everyone

Show the image models used for you and this channel.

{% endraw %}
