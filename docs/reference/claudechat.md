---
title: ClaudeChat
parent: Command reference
nav_order: 9
permalink: /reference/claudechat/
---

# ClaudeChat

Chat with Anthropic's Claude, which also answers questions about the bot and runs commands for you.

`!ai` talks in this channel's shared conversation, and `!aithread` starts a dedicated thread.
Reply to any of my answers to keep that conversation going.

Ask about the bot itself too ("how do I start a game vote?"), or ask it to do something.
`!butler` is the same as `!ai`.

For a task-by-task guide, see [AI chat and images]({{ '/ai/' | relative_url }}).

{% raw %}
<a id="ai"></a>
### !ai

`!ai [prompt]`

**Who:** everyone · **Also:** `!chat`, `!ask`, `!g`

Talk to Claude in this channel's shared conversation.

Everyone in the channel shares one conversation, so Claude can follow along
with multiple people. Attach images, PDFs, or text files and Claude will read them.
Reply to any of Claude's answers to keep going without typing the command.

Ask how to use the bot, or ask it to do something, and Claude looks up the
commands and can run them for you, with your own permissions. `!butler` is the same.

Start with "draw", "paint", or "image of" to go straight to the image generator
(Gemini). Other ways of asking for a picture work too; Claude hands them off.
Reply "make it blue" or similar to change the last image.

**Examples:**
- `!ai what's a good name for a guild?`
- `!ai how do I start a vote on what to play?`
- `!ai summarize this` (with a PDF attached)
- `!ai could you make us a banner with a dragon guarding a castle?`

<a id="ai-reset"></a>
### !ai reset

`!ai reset`

**Who:** mods, or anyone with the manage channels permission

Wipe this channel's shared conversation memory.

<a id="aithread"></a>
### !aithread

`!aithread <prompt>`

**Who:** everyone

Start a new thread for a conversation with Claude.

Inside the thread, @mention me or reply to my messages to keep talking.

<a id="butler"></a>
### !butler

`!butler [request]`

**Who:** everyone · **Also:** `!guide`

Ask how to use this bot, ask it to do something, or ask anything else, in plain English.

The same as `!ai`: it continues this channel's shared AI conversation. Ask "how do I…" and it
tells you what to type; ask it to do something and it runs the commands for you, with your own
permissions. Anything that needs mod, admin, or game admin rights waits for you to press Run.
Reply to its answers to follow up. You can also just @mention me.

**Examples:**
- `!butler how do I start a vote on what to play?`
- `!butler add Rocket League to my games and mark it installed`
- `!butler set up my gaming profile`

<a id="catchup"></a>
### !catchup

`!catchup`

**Who:** everyone

Get a summary of this channel since you last spoke, sent to you privately.

The text command sends it by DM; the `/catchup` slash command shows it only to you, right here.

<a id="claude"></a>
### !claude

`!claude`

**Who:** everyone

Claude AI settings and usage.

<a id="claude-channelmodel"></a>
### !claude channelmodel

`!claude channelmodel <model>`

**Who:** mods, or anyone with the manage channels permission

Pick the model for this channel's shared conversation and its AI threads. Use `reset` for the default.

<a id="claude-defaultpersona"></a>
### !claude defaultpersona

`!claude defaultpersona [persona]`

**Who:** admins, or anyone with the manage guild permission

Set the persona that `!claude persona reset` goes back to.

- `!claude defaultpersona <text>` saves new text as the default (or attach it as a `.txt` file).
- `!claude defaultpersona current` saves the persona in use right now.
- `!claude defaultpersona clear` goes back to ButlerBot's own persona.
- Run with nothing to see the saved default.

<a id="claude-guideactions"></a>
### !claude guideactions

`!claude guideactions <enabled>`

**Who:** admins, or anyone with the manage guild permission · **Also:** `!claude butleractions`

Let the AI chat run commands for people when they ask it to do something.

Commands always run with the asker's own permissions. Ones that need mod, admin, or
game admin rights wait for the asker to press Run. When off, it only explains.

<a id="claude-guidementions"></a>
### !claude guidementions

`!claude guidementions <enabled>`

**Who:** admins, or anyone with the manage guild permission · **Also:** `!claude butlermentions`

Turn on or off answering @mentions of the bot, and replies to its other messages, in the AI chat.

Applies outside AI threads, and uses the channel's shared AI conversation. Replies to AI chat answers
always continue that chat. The AI stays quiet when a reply is meant for other people ("I'm in!").

<a id="claude-limit"></a>
### !claude limit

`!claude limit <messages_per_day>`

**Who:** admins, or anyone with the manage guild permission

Limit how many AI messages each user can send per day (0 = unlimited).

Mods, admins, and the bot owner are exempt. Resets at midnight UTC.

<a id="claude-models"></a>
### !claude models

`!claude models`

**Who:** everyone

List the available Claude models and their prices.

<a id="claude-persona"></a>
### !claude persona

`!claude persona [persona]`

**Who:** admins, or anyone with the manage guild permission

Set Claude's personality and instructions for this server.

Applies to the AI chat and, as a speaking style, to the bot guide (whose command help stays exact).
Up to 8,000 characters. Discord messages stop at 2,000, so for a long persona attach it as a
`.txt` file to `!claude persona` instead of typing it.

Run with no text to see the current persona, or `reset` to go back to the server's default
persona (set with `!claude defaultpersona`), or ButlerBot's own persona if there isn't one.

**Example:** `!claude persona You are a grizzled pirate quartermaster. Keep answers short and salty.`

<a id="claude-resetusage"></a>
### !claude resetusage

`!claude resetusage`

**Who:** admins, or anyone with the manage guild permission

Reset this server's usage statistics and daily counts.

<a id="claude-settings"></a>
### !claude settings

`!claude settings`

**Who:** everyone

Show the current Claude settings for you, this channel, and this server.

<a id="claude-usage"></a>
### !claude usage

`!claude usage [member]`

**Who:** everyone

Show AI usage and estimated cost.

Your own usage is sent to you by DM, with a ✅ on your command. Admins see the server's totals and each
member's usage, or name a member to see theirs, right where they ask.

<a id="claude-websearch"></a>
### !claude websearch

`!claude websearch <enabled>`

**Who:** admins, or anyone with the manage guild permission

Turn web search on or off for this server (searches cost $10 per 1,000).

{% endraw %}
