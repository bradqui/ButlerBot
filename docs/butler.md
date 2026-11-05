---
title: Asking ButlerBot
nav_order: 3
permalink: /butler/
---

# Asking ButlerBot

Not sure which command you need? Ask in plain English. ButlerBot looks up the commands in this server, then explains what to type or does it for you.

```
!butler how do I find a game everyone owns?
!butler add Rocket League to my games and mark it installed
!butler set up my gaming profile
!butler what games do Alex and I both have installed?
```

`!butler`, `!guide` and `!ai` are all the same thing: one conversation per channel, so ask whichever way you like. You can also skip the command and @mention ButlerBot: "@ButlerBot when is the server busiest?"

## Questions vs. requests

- **"How do I…"** gets an explanation with the exact commands to type.
- **"Do this…"** gets it done. ButlerBot runs the commands **as you**, with your own permissions, as if you'd typed them.
  - Anything that needs mod, admin or game admin rights waits for you to press **Run** first.
  - It never runs a command you couldn't run yourself.

## Questions that aren't about the bot

Ask anything else too, like "summarize yesterday's election" or "help with my homework". It's the same [AI chat]({{ '/ai/' | relative_url }}), so you can mix the two in one question: "what's a good co-op game for four, and how do I add it to my library?"

Questions about using the bot don't count toward a daily AI limit, even when you've reached it. Everything else does.

## It can look things up

Before answering, ButlerBot can check real data:
- anyone's game library and wishlist;
- who owns or has installed a game, or whether it's been requested;
- running game sessions and votes;
- server stats like busy times, top posters and voice time. Admin-only stats stay admin-only.

## Following up

- **Reply** to one of ButlerBot's answers, or just ask again with `!butler` or `!ai`. It's the channel's shared conversation, so "and can I make that weekly?" follows on from what was just said.
- **Replying to the bot's other messages,** like a game announcement, also reaches ButlerBot. It stays quiet when your reply was clearly meant for other people.

## Mistyped a command?

If you type a command that doesn't exist, ButlerBot usually suggests the right one with a **Run it** button:

> ❓ `!game owns barony` isn't a command. Did you mean `!games own barony`?

## When it doesn't know

If nothing the bot has fits your question, ButlerBot says so plainly. Admins see those questions in the [stats]({{ '/stats/' | relative_url }}), so missing features get noticed.

{: .staff }
> Admins control this with:
> - `!claude guidementions on|off`, whether @mentions and replies to the bot's posts reach it;
> - `!claude guideactions on|off`, whether it may run commands.
>
> It uses the channel's AI model (`!claude channelmodel`). The bot owner picks the quick model, used for typo suggestions, with `!claude quickmodel`.
