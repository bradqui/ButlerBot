---
title: Filters and spam
nav_order: 21
permalink: /filters/
---

# Filters and spam

For mods and admins. Three layers keep chat clean: **Censord** (our word filter, with levels and punishments), Red's **Filter**, and **AntiSpam** for command spam.

## Censord: leveled word filter

Each channel has a level:
- **off**
- **low** (only the low list)
- **high** (both lists)

Messages with a listed word are deleted. Repeat offenders can be punished automatically.

| Command | What it does |
|---|---|
| `!censor config` | Dashboard of the current setup. |
| `!censor level <off\|low\|high> [#channel]` | Set the level for the server, or for one channel. |
| `!censor addword <low\|high> <word>` / `delword` | Add or remove a word. `*` is a wildcard (`bad*` matches "badly"). Without one, only whole words match. |
| `!censor strategy <mode>` | Watch every channel except some (`exclude`), or only some (`include`). |
| `!censor exceptchan` / `includechan <#channel>` | Toggle channels for that strategy. |
| `!censor threshold <count> <seconds>` | How many hits within how many seconds trigger a punishment. |
| `!censor action <action> [#channel]` | The punishment: delete, kick or ban. |
| `!censor setrole [role]` | A role allowed to change Censord settings. |
| `!censor reload` | Reload the word lists after editing them on the server. |

**Who's exempt:** mods and admins.

**Word lists:** CSV files on the bot's server. Edit them there, then run `!censor reload`.

## Red's Filter

A simpler server-wide or per-channel list of banned words and phrases. It matches whole words only, so "ass" doesn't match "class".

| Command | Who |
|---|---|
| `!filter add <words…>` / `delete <words…>` | Mod or Manage Messages |
| `!filter list` | Mod or Manage Messages (sent to your DMs) |
| `!filter channel add <#channel> <words…>` | Mod or Manage Messages |
| `!filter names` | Also filter nicknames and usernames |
| `!filterset ban <count> <seconds>` | Auto-ban repeat offenders (admin) |

Put phrases in quotes: `!filter add "some phrase"`.

{: .note }
> Filter does **not** exempt mods and admins. Use `!autoimmune add <user or role>` for anyone who should be exempt.

## AntiSpam: command flooding

Running **5 commands within 5 seconds** blocks someone from using bot commands for **5 minutes**. They get a "slow down" notice, and their commands are ignored until the block ends.

**Scope:**
- Only bot commands count, not regular chat.
- Mods and admins are exempt.

**Settings:** only the bot owner can tune it (`!antispamset …`), and the settings apply to every server the bot is in.

## Also see

- **Automatic actions on spam** (mention spam, repeated messages): [Moderation → Automod]({{ '/moderation/' | relative_url }}#automod).
- **Slowmode:** `!slowmode 10s`.
