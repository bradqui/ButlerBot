---
title: Getting started
nav_order: 2
permalink: /start/
---

# Getting started

Welcome! Here's how to get set up in a few minutes.

## 1. Pick your role when you join

When you join, ButlerBot greets you with buttons:
1. **Pick your group.** ButlerBot adds its tag to your nickname, like `[TAG] YourName`.
2. **Agree to the rules.** That unlocks the rest of the server.

Picked the wrong group? Fix it yourself with the button's exact label:

```
!changerole <button label>
```

## 2. Set up your gaming profile

One command walks you through everything, step by step:

```
!games newprofile
```

You'll set:
- your timezone;
- the games you own and have installed;
- your top 3 favorites;
- a wishlist of games you want, so you get pinged when one goes on sale.

Every step is optional. You can also just tell ButlerBot: "@ButlerBot set up my profile". More in [Your games]({{ '/games/library/' | relative_url }}).

## 3. Know where to ask

- **Plain English:** `!butler how do I…` or @mention ButlerBot. It explains, or does it for you. See [Asking ButlerBot]({{ '/butler/' | relative_url }}).
- **One command:** `!help <command>`.
- **Everything:** this handbook. `!handbook` posts the link in Discord.

## Things worth knowing

- **AI chat:** `!ai <message>` talks to Claude in the channel. See [AI chat and images]({{ '/ai/' | relative_url }}).
- **Game nights:** people post sessions you can join with a button. See [Game nights]({{ '/games/nights/' | relative_url }}).
- **Reminders:** `!remindme 2h check the oven`.
- **Right-click tools:** right-click a message → **Apps** for **Summarize link** (a private summary of an article or video) and **Translate**. Both show results only to you.
- **Privacy:**
  - ButlerBot counts activity for [Server stats]({{ '/stats/' | relative_url }}). It counts hourly totals and never stores message text. `!stats ignoreme` opts you out.
  - `!speakup me off` stops the bot reacting to your messages on its own.
