---
title: Asking ButlerBot
nav_order: 3
permalink: /butler/
---

# Asking ButlerBot

Not sure which command you need? Ask in plain English. ButlerBot knows every command in the server. It explains what to type, or does it for you.

```
!butler how do I find a game everyone owns?
!butler add Rocket League to my games and mark it installed
!butler set up my gaming profile
!butler what games do Alex and I both have installed?
```

`!guide` works too; it's the same thing. You can also skip the command and @mention ButlerBot: "@ButlerBot when is the server busiest?"

## Questions vs. requests

- **"How do I…"** gets an explanation with the exact commands to type.
- **"Do this…"** gets it done. ButlerBot runs the commands **as you**, with your own permissions, as if you'd typed them.
  - Anything that needs mod, admin or game admin rights waits for you to press **Run** first.
  - It never runs a command you couldn't run yourself.

## Questions that aren't about the bot

Ask ButlerBot something unrelated, like "summarize yesterday's election" or "help with my homework", and it passes the question to the [AI chat]({{ '/ai/' | relative_url }}). You get the same answer as `!ai`, in the channel's shared AI conversation. **The handoff:**
- counts toward any daily AI limit;
- only happens where you're allowed to use `!ai`.

## It can look things up

Before answering, ButlerBot can check real data:
- anyone's game library and wishlist;
- who owns or has installed a game, or whether it's been requested;
- running game sessions and votes;
- server stats like busy times, top posters and voice time. Admin-only stats stay admin-only.

## Following up

- **Reply** to one of ButlerBot's answers to continue the conversation. It remembers your last few questions for about 15 minutes.
- **Replying to the bot's other messages,** like a game announcement, also reaches ButlerBot. It stays quiet when your reply was clearly meant for other people.

## Mistyped a command?

If you type a command that doesn't exist, ButlerBot usually suggests the right one with a **Run it** button:

> ❓ `!game owns barony` isn't a command. Did you mean `!games own barony`?

## When it doesn't know

If nothing the bot has fits your question, ButlerBot says so plainly. Admins see those questions in the [stats]({{ '/stats/' | relative_url }}), so missing features get noticed.

{: .staff }
> Admins control this with:
> - `!claude guidementions on|off`, whether @mentions and replies reach the butler;
> - `!claude guideactions on|off`, whether it may run commands;
> - `!claude butlerhandoff on|off`, whether off-topic questions go to the AI chat (otherwise it just suggests `!ai`).
>
> The bot owner picks its model with `!claude guidemodel`.
