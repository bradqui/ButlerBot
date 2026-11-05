---
title: ClaudeChat
parent: Command reference
nav_order: 11
permalink: /reference/claudechat/
---

# ClaudeChat

Chat with Anthropic's Claude.

`!ai` talks in this channel's shared conversation, `!myai` keeps a private
conversation that follows you around, and `!aithread` starts a dedicated thread.
Reply to any of my answers to keep that conversation going.

`!butler` answers questions about the bot itself, like "how do I start a game vote?"

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

Start with "draw", "paint", or "image of" to go straight to the image generator
(Gemini). Other ways of asking for a picture work too; Claude hands them off.
Reply "make it blue" or similar to change the last image.

**Examples:**
- `!ai what's a good name for a guild?`
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

Ask how to use this bot, or ask it to do something, in plain English.

The butler knows every command enabled in this server. Ask "how do I…" and it tells you
what to type; ask it to do something and it runs the commands for you, with your own
permissions. Anything that needs mod, admin, or game admin rights waits for you to press Run.
Reply to its answers to follow up. You can also just @mention me.

**Examples:**
- `!butler how do I start a vote on what to play?`
- `!butler add Rocket League to my games and mark it installed`
- `!butler set up my gaming profile`

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
- `!claude defaultpersona clear` goes back to the built-in default.
- Run with nothing to see the saved default.

<a id="claude-guideactions"></a>
### !claude guideactions

`!claude guideactions <enabled>`

**Who:** admins, or anyone with the manage guild permission · **Also:** `!claude butleractions`

Let the bot guide run commands for people when they ask it to do something.

Commands always run with the asker's own permissions. Ones that need mod, admin, or
game admin rights wait for the asker to press Run. When off, the guide only explains.

<a id="claude-guidehandoff"></a>
### !claude guidehandoff

`!claude guidehandoff <enabled>`

**Who:** admins, or anyone with the manage guild permission · **Also:** `!claude butlerhandoff`

Pass questions that aren't about the bot from the butler to the AI chat.

When on, asking `!butler` (or @mentioning the bot) something like "who won the game last night?" gets an
answer from the AI chat, as if it had been asked with `!ai`. It uses the channel's shared AI conversation,
counts toward the daily AI limit, and only happens where the asker may use `!ai`. When off, the butler
just suggests `!ai`.

<a id="claude-guidementions"></a>
### !claude guidementions

`!claude guidementions <enabled>`

**Who:** admins, or anyone with the manage guild permission · **Also:** `!claude butlermentions`

Turn on or off sending @mentions of the bot, and replies to its messages, to the bot guide.

Applies outside AI threads. Replies to AI chat answers always continue that chat.
The guide stays quiet when a reply is meant for other people ("I'm in!").

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

<a id="claude-mymodel"></a>
### !claude mymodel

`!claude mymodel <model>`

**Who:** admins, or anyone with the manage guild permission

Pick the model for your private conversations (`!myai`). Admins only. Use `reset` for the default.

Only models the bot owner allows can be picked (see `!claude models`).

<a id="claude-persona"></a>
### !claude persona

`!claude persona [persona]`

**Who:** admins, or anyone with the manage guild permission

Set Claude's personality and instructions for this server.

Applies to the AI chat and, as a speaking style, to the bot guide (whose command help stays exact).
Up to 3,000 characters. Discord messages stop at 2,000, so for a long persona attach it as a
`.txt` file to `!claude persona` instead of typing it.

Run with no text to see the current persona, or `reset` to go back to the server's default
persona (set with `!claude defaultpersona`).

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

Show Claude usage and estimated cost.

Admins see the server's totals and top users (or a specific member's).
Everyone else sees their own.

<a id="claude-websearch"></a>
### !claude websearch

`!claude websearch <enabled>`

**Who:** admins, or anyone with the manage guild permission

Turn web search on or off for this server (searches cost $10 per 1,000).

<a id="myai"></a>
### !myai

`!myai [prompt]`

**Who:** everyone

Talk to Claude in your own private conversation.

Your private conversation follows you across channels and only you can
continue it (by command or by replying to its answers). It uses the bot's
default model; admins can pick their own with `!claude mymodel`.

<a id="myai-reset"></a>
### !myai reset

`!myai reset`

**Who:** everyone

Wipe your private conversation memory.

{% endraw %}
