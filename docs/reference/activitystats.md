---
title: ActivityStats
parent: Command reference
nav_order: 2
permalink: /reference/activitystats/
---

# ActivityStats

Server activity stats: channels, leaderboards, busy times, voice and games, plus admin reports.

For a task-by-task guide, see [Server stats]({{ '/stats/' | relative_url }}).

{% raw %}
<a id="stats"></a>
### !stats

`!stats [period]`

**Who:** everyone

Server activity stats.

With no subcommand, shows the last week at a glance. Periods look like `week`, `month`, `90d` or `all`.

<a id="stats-admin"></a>
### !stats admin

`!stats admin`

**Who:** admins, or anyone with the manage guild permission

Admin-only reports and stats settings.

<a id="stats-admin-active"></a>
### !stats admin active

`!stats admin active [period]`

**Who:** admins, or anyone with the manage guild permission

Daily, weekly and monthly active members over time. Default: 90 days.

<a id="stats-admin-attendance"></a>
### !stats admin attendance

`!stats admin attendance [count=10]`

**Who:** admins, or anyone with the manage guild permission

Recent game sessions: who clicked Join and who showed up in voice.

<a id="stats-admin-backfill"></a>
### !stats admin backfill

`!stats admin backfill [days=30]`

**Who:** admins, or anyone with the manage guild permission

Count messages from before tracking started by reading channel history (up to 90 days back).

Only message counts can be backfilled; voice time and games can't. This can take a while on busy servers.

<a id="stats-admin-commands"></a>
### !stats admin commands

`!stats admin commands [period]`

**Who:** admins, or anyone with the manage guild permission

Command usage, unused cogs, and commands people typed that don't exist. Default: 30 days.

<a id="stats-admin-deadchannels"></a>
### !stats admin deadchannels

`!stats admin deadchannels [period]`

**Who:** admins, or anyone with the manage guild permission · **Also:** `!stats admin dead`

Channels with no posts in a while. Default: 30 days.

<a id="stats-admin-digest"></a>
### !stats admin digest

`!stats admin digest`

**Who:** admins, or anyone with the manage guild permission

The weekly digest for admins. Turn it on, pick the channel and time, or preview it.

<a id="stats-admin-digest-channel"></a>
### !stats admin digest channel

`!stats admin digest channel <channel>`

**Who:** admins, or anyone with the manage guild permission

Choose where the digest is posted. Pick an admin-only channel.

<a id="stats-admin-digest-off"></a>
### !stats admin digest off

`!stats admin digest off`

**Who:** admins, or anyone with the manage guild permission

Turn the weekly digest off.

<a id="stats-admin-digest-on"></a>
### !stats admin digest on

`!stats admin digest on`

**Who:** admins, or anyone with the manage guild permission

Turn the weekly digest on.

<a id="stats-admin-digest-preview"></a>
### !stats admin digest preview

`!stats admin digest preview`

**Who:** admins, or anyone with the manage guild permission · **Also:** `!stats admin digest now`

Show this week's digest here.

<a id="stats-admin-digest-time"></a>
### !stats admin digest time

`!stats admin digest time <day> <hour>`

**Who:** admins, or anyone with the manage guild permission

Choose the day and hour, in the server's GameManager timezone. Example: `monday 9am`.

<a id="stats-admin-exclude"></a>
### !stats admin exclude

`!stats admin exclude <channel>`

**Who:** admins, or anyone with the manage guild permission

Stop tracking a channel (and its threads). Existing counts are deleted.

<a id="stats-admin-gametracking"></a>
### !stats admin gametracking

`!stats admin gametracking <enabled>`

**Who:** admins, or anyone with the manage guild permission

Turn recording of games played (from Discord's "Playing" status) on or off.

<a id="stats-admin-include"></a>
### !stats admin include

`!stats admin include <channel>`

**Who:** admins, or anyone with the manage guild permission

Start tracking an excluded channel again.

<a id="stats-admin-joins"></a>
### !stats admin joins

`!stats admin joins [period]`

**Who:** admins, or anyone with the manage guild permission

Joins and leaves over time. Default: 90 days.

<a id="stats-admin-libraries"></a>
### !stats admin libraries

`!stats admin libraries`

**Who:** admins, or anyone with the manage guild permission

How many members have set up a game library.

<a id="stats-admin-quiet"></a>
### !stats admin quiet

`!stats admin quiet`

**Who:** admins, or anyone with the manage guild permission · **Also:** `!stats admin lurkers`

Members who went quiet, and members with no messages or voice in 30 days.

<a id="stats-admin-retention"></a>
### !stats admin retention

`!stats admin retention [period]`

**Who:** admins, or anyone with the manage guild permission

Of the people who joined, how many posted in their first week and are still around. Default: 90 days.

<a id="stats-admin-settings"></a>
### !stats admin settings

`!stats admin settings`

**Who:** admins, or anyone with the manage guild permission

Show the stats settings.

<a id="stats-admin-unmet"></a>
### !stats admin unmet

`!stats admin unmet [period]`

**Who:** admins, or anyone with the manage guild permission

Questions the bot guide couldn't match to any command. Default: 30 days.

<a id="stats-channel"></a>
### !stats channel

`!stats channel [channel] [period]`

**Who:** everyone

One channel's activity and top posters. Default: this channel, the last month.

<a id="stats-channels"></a>
### !stats channels

`!stats channels [period]`

**Who:** everyone

Messages per day in each channel. Default: the last month.

<a id="stats-games"></a>
### !stats games

`!stats games [period]`

**Who:** everyone

The server's most-played games, from Discord's "Playing" status.

<a id="stats-heatmap"></a>
### !stats heatmap

`!stats heatmap [channel] [period]`

**Who:** everyone · **Also:** `!stats busy`, `!stats when`

When the server (or one channel) is busiest, by day and hour, in your timezone.

<a id="stats-ignoreme"></a>
### !stats ignoreme

`!stats ignoreme`

**Who:** everyone · **Also:** `!stats optout`

Stop tracking your activity, everywhere, and delete what's been recorded about you.

<a id="stats-me"></a>
### !stats me

`!stats me [member] [period]`

**Who:** everyone

Your own stats: messages, channels, usual hours, voice, games and game nights.

Your numbers are sent to you by DM, with a ✅ on your command. Admins can name a member to see theirs right
where they ask.

<a id="stats-top"></a>
### !stats top

`!stats top [channel] [period]`

**Who:** everyone · **Also:** `!stats leaderboard`, `!stats lb`

Who posted the most, server-wide or in one channel.

Examples: `!stats top`, `!stats top week`, `!stats top #general all`. Default: the last month.

<a id="stats-trackme"></a>
### !stats trackme

`!stats trackme`

**Who:** everyone · **Also:** `!stats optin`

Turn activity tracking back on for yourself.

<a id="stats-voice"></a>
### !stats voice

`!stats voice [period]`

**Who:** everyone

Time in each voice channel, who spends the most time there, and the most people at once.

{% endraw %}
