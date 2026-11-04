---
title: SpeakUp
parent: Command reference
nav_order: 29
permalink: /reference/speakup/
---

# SpeakUp

The bot chiming in when it can help: times, Steam links, link summaries, command mistakes, and reminders.

For a task-by-task guide, see [Reminders and auto-replies]({{ '/speakup/' | relative_url }}).

{% raw %}
<a id="reminders"></a>
### !reminders

`!reminders`

**Who:** everyone

List your reminders. `cancel <id>` or `clear` removes them.

<a id="reminders-cancel"></a>
### !reminders cancel

`!reminders cancel <reminder_id>`

**Who:** everyone · **Also:** `!reminders delete`, `!reminders remove`

Cancel one of your reminders by its ID.

<a id="reminders-clear"></a>
### !reminders clear

`!reminders clear`

**Who:** everyone

Cancel all of your reminders.

<a id="remindme"></a>
### !remindme

`!remindme <when_and_what>`

**Who:** everyone · **Also:** `!remind`

Get a reminder later. Start with when, then what.

Times can be relative (`10m`, `2h`, `1d 3h`, `2 weeks`) or, with GameManager loaded, a time in your
timezone (`9pm`, `tomorrow 8am`, `friday 6pm`, `11/14 7pm`). The reminder pings you here, or in DMs if
this channel is gone.

**Examples:**
- `!remindme 2h check the oven`
- `!remindme friday 6pm buy Helldivers`
- `!remindme tomorrow 9am to call the dentist`

<a id="speakup"></a>
### !speakup

`!speakup`

**Who:** everyone

When the bot chimes in on its own, and how to quiet it.

The bot reacts to times in chat (click the clock to see the time in everyone's timezone), posts a card for
Steam store links, offers a summary of article and video links (click the page icon), and suggests the
right command when one is mistyped. It never pings anyone for these.

<a id="speakup-feature"></a>
### !speakup feature

`!speakup feature <feature> <enabled>`

**Who:** admins, or anyone with the manage guild permission

Turn one feature on or off server-wide: times, steam, links or mistakes.

<a id="speakup-me"></a>
### !speakup me

`!speakup me <enabled>`

**Who:** everyone

Turn it off (or back on) for your own messages: no reactions, cards or suggestions on them.

<a id="speakup-off"></a>
### !speakup off

`!speakup off [channel]`

**Who:** mods, or anyone with the manage channels permission

Quiet the bot in a channel (this one by default). Commands and reminders still work.

<a id="speakup-on"></a>
### !speakup on

`!speakup on [channel]`

**Who:** mods, or anyone with the manage channels permission

Let the bot chime in again in a channel (this one by default).

{% endraw %}
