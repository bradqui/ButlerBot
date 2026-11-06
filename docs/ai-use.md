---
title: What uses AI
nav_order: 4.5
permalink: /ai-use/
---

# What uses AI

Most of ButlerBot doesn't use AI at all. AI runs only when someone asks for it with one of the commands below, plus two helpers that use it as a last resort.

Nothing you write is sent to an AI service unless one of the things on this page happens.

## Commands that use AI

These run only when someone uses them. The text goes to Anthropic's Claude, and pictures are made by Google's Gemini.

| Command | What the AI does | What it's sent |
|---|---|---|
| `!ai` (also `!chat`, `!ask`, `!g`), `!aithread`, `!butler` (also `!guide`) | The [AI chat]({{ '/ai/' | relative_url }}) | That conversation, and any files attached to it |
| @mentioning ButlerBot, or replying to one of its messages | Goes to the AI chat too | Your message, and the one you replied to |
| `!draw`, `!draw edit` | Makes a picture | Your description |
| `!catchup`, `/catchup` | Sums up what you missed | The channel's messages since you last spoke (up to 400) |
| `!judge` (also `!verdict`) | Rules on an argument | The channel's last 20–60 messages |
| `!adventure` | Narrates a text adventure in its own thread | The players' messages in that thread, and their character bios |
| `!maketrivia` (mods) | Writes trivia questions | The topic. For "our games", the server's game list. |
| `!guessgame` | Describes and draws a game for people to guess | The game's name |
| Right-click → **Apps** → **Summarize link**, or clicking 📄 under a link | Sums up the article | The link. The 📄 is added without AI; AI runs only if someone clicks it. |

## Helpers that use AI as a last resort

- **Mistyped commands:** when a command isn't recognized, ButlerBot first tries a plain spelling match. Only if that finds nothing does it ask the AI, sending just what you typed and your display name.
- **New game names** (`!games request`, `!games admin add`, and the Request or Add buttons): ButlerBot checks the server's library first, then Steam's store. Only if both come up empty does it ask the AI, sending just the game name.

## Everything else is AI-free

- **Games:** the game library, game nights, votes, reminders and Discord events.
- **Server stats** and their charts.
- **Help:** `!help` and this handbook.
- **Automatic replies:** the 🕘 time conversion follows fixed rules, and Steam cards use Steam's own data.
- **Welcome, filters and moderation.**
- **Voice rooms.**
- **Playing trivia:** `!trivia` uses ready-made question lists. Lists whose names start with `bb_` were written with `!maketrivia`.

**Translation** uses Google Translate. That's machine translation rather than a chatbot, but it's worth knowing if you'd rather avoid anything of the kind.

## Opting out

`!speakup me off` stops ButlerBot's automatic replies to your messages, including the typo suggestions. Everything else above only happens when you use it.

{: .staff }
> **Turning AI features off for the server:**
> - `!speakup feature mistakes off` stops the AI typo suggestions.
> - `!speakup feature links off` stops the 📄 summary offers.
> - `!claude guidementions off` stops @mentions, and replies to the bot's other messages, from reaching the AI chat. Replying to an AI answer, `!ai` and `!butler` still work.
> - To switch AI off completely, the bot owner can run `!unload claude gemini butlerfun`. Everything in the first two sections then stops, and the game name check skips its last step. `!load` brings them back.
