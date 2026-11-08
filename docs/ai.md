---
title: AI chat and images
nav_order: 4
permalink: /ai/
---

# AI chat and images

ButlerBot chats using Anthropic's Claude and draws pictures with Google's Gemini. To see which other features use AI, and which don't, see [What uses AI]({{ '/ai-use/' | relative_url }}).

## Two ways to chat

| Command | Who sees it | Good for |
|---|---|---|
| `!ai <message>` (also `!chat`, `!ask`, `!g`) | The whole channel shares one conversation | Group questions and banter |
| `!aithread <message>` | A new thread just for that conversation | Long discussions without cluttering the channel |

**Keeping a conversation going:**
- **Reply** to any of ButlerBot's AI answers to continue that conversation.
- In an AI thread, @mention ButlerBot or reply to its messages.

**What it can do:**
- **The bot itself:** ask how to use ButlerBot, or ask it to do something, and it looks up the commands and can run them for you. See [Asking ButlerBot]({{ '/butler/' | relative_url }}); `!butler` is the same conversation as `!ai`.
- **Attachments:** it reads images, PDFs and text files you attach, or ones in the message you reply to.
- **Web search:** it searches the web when it needs current information, and lists its sources under the answer.
- **Tagging people:** it can tag people it talks about. These are highlighted mentions that don't ping anyone.

**Starting fresh:**
- **Idle reset:** conversations reset after a while without activity, and when the bot restarts.
- `!ai reset` wipes the channel's (mods).

## Catching up on a busy channel

```
/catchup
```

You get a short summary of everything since you last spoke in the channel, and only you see it. The text version `!catchup` sends it to your DMs instead.

## Summarizing links

ButlerBot can read an article and sum it up in three lines (videos can't be summarized):
- **Privately:** right-click the message with the link → **Apps** → **Summarize link**. Only you see it.
- **For the channel:** click the 📄 under the link.

## Making images

Just ask in an AI chat, starting with "draw" or "image of":

```
!ai draw a castle made of cheese at sunset
!ai make it night time
```

Or use Gemini directly:

```
!draw a robot butler polishing a teacup
!draw edit add a tiny top hat
```

`!draw edit` (or "make it…" right after an image) changes the last image instead of starting over.

## Limits and costs

- AI use costs real money, so admins may set a **daily limit** per person (`!claude limit`).
  - Mods and admins aren't limited.
  - Questions about using the bot don't count.
  - When you hit it, ButlerBot says so; it resets at midnight UTC.
- `!claude usage` sends your own usage and estimated cost to your DMs, and puts a ✅ on your command. If your DMs are closed, it's posted in the channel instead.

## Personality

ButlerBot comes with its own personality: a slightly put-upon robot butler who runs "the Manor." It applies everywhere the bot uses AI, and a server's admins can replace or adjust it.

{: .staff }
> **Admin settings** (`!claude …`):
> - `persona [text]` and `defaultpersona [text|current|clear]` set the personality. You can attach a `.txt` file for long ones (up to 8,000 characters). `persona reset` goes back to the server's saved default, or to ButlerBot's own when there isn't one.
> - `websearch on|off`
> - `limit <per day>`
> - `usage [member]`: the server's totals and every member's usage, or one member's usage, shown where you ask
> - `resetusage`
>
> **Mods:** `!claude channelmodel <model|reset>` picks the model for a channel and its threads.
>
> **Gemini:** `!gemini channelmodel` sets a channel's image model; see `!gemini list` and `!gemini settings`. Use `image`, `3image` or a name from `!gemini list`; other names are turned down.
>
> The bot owner sets the default model, effort and memory length, and the API keys.
