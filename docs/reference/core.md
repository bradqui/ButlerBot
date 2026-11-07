---
title: Core
parent: Command reference
nav_order: 12
permalink: /reference/core/
---

# Core

The Core cog has many commands related to core functions.

These commands come loaded with every Red bot, and cover some of the most basic usage of the bot.

{% raw %}
<a id="autoimmune"></a>
### !autoimmune

`!autoimmune`

**Who:** server owners, or anyone with the manage guild permission

Commands to manage server settings for immunity from automated actions.

This includes duplicate message deletion and mention spam from the Mod cog, and filters from the Filter cog.

<a id="autoimmune-add"></a>
### !autoimmune add

`!autoimmune add <user_or_role>`

**Who:** server owners, or anyone with the manage guild permission

Makes a user or role immune from automated moderation actions.

**Examples:**
- `!autoimmune add @Twentysix` - Adds a user.
- `!autoimmune add @Mods` - Adds a role.

**Arguments:**
- `<user_or_role>` - The user or role to add immunity to.

<a id="autoimmune-isimmune"></a>
### !autoimmune isimmune

`!autoimmune isimmune <user_or_role>`

**Who:** server owners, or anyone with the manage guild permission

Checks if a user or role would be considered immune from automated actions.

**Examples:**
- `!autoimmune isimmune @Twentysix`
- `!autoimmune isimmune @Mods`

**Arguments:**
- `<user_or_role>` - The user or role to check the immunity of.

<a id="autoimmune-list"></a>
### !autoimmune list

`!autoimmune list`

**Who:** server owners, or anyone with the manage guild permission

Gets the current members and roles configured for automatic moderation action immunity.

**Example:**
- `!autoimmune list`

<a id="autoimmune-remove"></a>
### !autoimmune remove

`!autoimmune remove <user_or_role>`

**Who:** server owners, or anyone with the manage guild permission

Remove a user or role from being immune to automated moderation actions.

**Examples:**
- `!autoimmune remove @Twentysix` - Removes a user.
- `!autoimmune remove @Mods` - Removes a role.

**Arguments:**
- `<user_or_role>` - The user or role to remove immunity from.

<a id="bankset"></a>
### !bankset

`!bankset`

**Who:** server owners, or anyone with the administrator permission

Base command for bank settings.

<a id="bankset-bankname"></a>
### !bankset bankname

`!bankset bankname <name>`

**Who:** server owners, or anyone with the administrator permission

Set the bank's name.

<a id="bankset-creditsname"></a>
### !bankset creditsname

`!bankset creditsname <name>`

**Who:** server owners, or anyone with the administrator permission

Set the name for the bank's currency.

<a id="bankset-maxbal"></a>
### !bankset maxbal

`!bankset maxbal <amount>`

**Who:** server owners, or anyone with the administrator permission

Set the maximum balance a user can get.

<a id="bankset-prune"></a>
### !bankset prune

`!bankset prune`

**Who:** admins, or anyone with the manage guild permission

Base command for pruning bank accounts.

<a id="bankset-prune-server"></a>
### !bankset prune server

`!bankset prune server [confirmation=False]`

**Who:** server owners only · **Also:** `!bankset prune guild`, `!bankset prune local`

Prune bank accounts for users no longer in the server.

Cannot be used with a global bank. See `!bankset prune global`.

Examples:
- `!bankset prune server` - Did not confirm. Shows the help message.
- `!bankset prune server yes`

**Arguments**

- `<confirmation>` This will default to false unless specified.

<a id="bankset-prune-user"></a>
### !bankset prune user

`!bankset prune user <user> [confirmation=False]`

**Who:** admins, or anyone with the manage guild permission

Delete the bank account of a specified user.

Examples:
- `!bankset prune user @Twentysix` - Did not confirm. Shows the help message.
- `!bankset prune user @Twentysix yes`

**Arguments**

- `<user>` The user to delete the bank of. Takes mentions, names, and user ids.
- `<confirmation>` This will default to false unless specified.

<a id="bankset-registeramount"></a>
### !bankset registeramount

`!bankset registeramount <creds>`

**Who:** server owners, or anyone with the administrator permission

Set the initial balance for new bank accounts.

Example:
- `!bankset registeramount 5000`

**Arguments**

- `<creds>` The new initial balance amount. Default is 0.

<a id="bankset-reset"></a>
### !bankset reset

`!bankset reset [confirmation=False]`

**Who:** server owners, or anyone with the administrator permission

Delete all bank accounts.

Examples:
- `!bankset reset` - Did not confirm. Shows the help message.
- `!bankset reset yes`

**Arguments**

- `<confirmation>` This will default to false unless specified.

<a id="bankset-showsettings"></a>
### !bankset showsettings

`!bankset showsettings`

**Who:** server owners, or anyone with the administrator permission

Show the current bank settings.

<a id="command"></a>
### !command

`!command`

**Who:** server owners, or anyone with the administrator permission

Commands to enable and disable commands and cogs.

<a id="command-disable"></a>
### !command disable

`!command disable <command>`

**Who:** server owners, or anyone with the administrator permission

Disable a command.

If you're the bot owner, this will disable commands globally by default.
Otherwise, this will disable commands on the current server.

**Examples:**
- `!command disable userinfo` - Disables the `userinfo` command in the Mod cog.
- `!command disable urban` - Disables the `urban` command in the General cog.

**Arguments:**
- `<command>` - The command to disable.

<a id="command-disable-server"></a>
### !command disable server

`!command disable server <command>`

**Who:** server owners, or anyone with the administrator permission · **Also:** `!command disable guild`

Disable a command in this server only.

**Examples:**
- `!command disable server userinfo` - Disables the `userinfo` command in the Mod cog.
- `!command disable server urban` - Disables the `urban` command in the General cog.

**Arguments:**
- `<command>` - The command to disable for the current server.

<a id="command-disablecog"></a>
### !command disablecog

`!command disablecog <cog>`

**Who:** server owners, or anyone with the administrator permission

Disable a cog in this server.

Note: This will only work on loaded cogs, and must reference the title-case cog name.

**Examples:**
- `!command disablecog Economy`
- `!command disablecog ModLog`

**Arguments:**
- `<cog>` - The name of the cog to disable on this server. Must be title-case.

<a id="command-enable"></a>
### !command enable

`!command enable <command>`

**Who:** server owners, or anyone with the administrator permission

Enable a command.

If you're the bot owner, this will try to enable a globally disabled command by default.
Otherwise, this will try to enable a command disabled on the current server.

**Examples:**
- `!command enable userinfo` - Enables the `userinfo` command in the Mod cog.
- `!command enable urban` - Enables the `urban` command in the General cog.

**Arguments:**
- `<command>` - The command to enable.

<a id="command-enable-server"></a>
### !command enable server

`!command enable server <command>`

**Who:** server owners, or anyone with the administrator permission · **Also:** `!command enable guild`

Enable a command in this server.

**Examples:**
- `!command enable server userinfo` - Enables the `userinfo` command in the Mod cog.
- `!command enable server urban` - Enables the `urban` command in the General cog.

**Arguments:**
- `<command>` - The command to enable for the current server.

<a id="command-enablecog"></a>
### !command enablecog

`!command enablecog <cog>`

**Who:** server owners, or anyone with the administrator permission

Enable a cog in this server.

Note: This will only work on loaded cogs, and must reference the title-case cog name.

**Examples:**
- `!command enablecog Economy`
- `!command enablecog ModLog`

**Arguments:**
- `<cog>` - The name of the cog to enable on this server. Must be title-case.

<a id="command-listdisabled"></a>
### !command listdisabled

`!command listdisabled`

**Who:** server owners, or anyone with the administrator permission

List disabled commands.

If you're the bot owner, this will show global disabled commands by default.
Otherwise, this will show disabled commands on the current server.

**Example:**
- `!command listdisabled`

<a id="command-listdisabled-global"></a>
### !command listdisabled global

`!command listdisabled global`

**Who:** server owners, or anyone with the administrator permission

List disabled commands globally.

**Example:**
- `!command listdisabled global`

<a id="command-listdisabled-guild"></a>
### !command listdisabled guild

`!command listdisabled guild`

**Who:** server owners, or anyone with the administrator permission

List disabled commands in this server.

**Example:**
- `!command listdisabled guild`

<a id="command-listdisabledcogs"></a>
### !command listdisabledcogs

`!command listdisabledcogs`

**Who:** server owners, or anyone with the administrator permission

List the cogs which are disabled in this server.

**Example:**
- `!command listdisabledcogs`

<a id="contact"></a>
### !contact

`!contact <message>`

**Who:** everyone

Sends a message to the owner.

This is limited to one message every 60 seconds per person.

**Example:**
- `!contact Help! The bot has become sentient!`

**Arguments:**
- `[message]` - The message to send to the owner.

<a id="embedset"></a>
### !embedset

`!embedset`

**Who:** everyone

Commands for toggling embeds on or off.

This setting determines whether or not to use embeds as a response to a command (for commands that support it).
The default is to use embeds.

The embed settings are checked until the first True/False in this order:

- In guild context:
  1. Channel override - `!embedset channel`
  2. Server command override - `!embedset command server`
  3. Server override - `!embedset server`
  4. Global command override - `!embedset command global`
  5. Global setting  -`!embedset global`

- In DM context:
  1. User override - `!embedset user`
  2. Global command override - `!embedset command global`
  3. Global setting - `!embedset global`

<a id="embedset-channel"></a>
### !embedset channel

`!embedset channel <channel> [enabled]`

**Who:** server owners, or anyone with the administrator permission

Set's a channel's embed setting.

If set, this is used instead of the guild and command defaults to determine whether or not to use embeds.
This is used for all commands done in a channel.

If enabled is left blank, the setting will be unset and the guild default will be used instead.

To see full evaluation order of embed settings, run `!help embedset`.

**Examples:**
- `!embedset channel #text-channel False` - Disables embeds in the #text-channel.
- `!embedset channel #forum-channel disable` - Disables embeds in the #forum-channel.
- `!embedset channel #text-channel` - Resets value to use guild default in the #text-channel.

**Arguments:**
    - `<channel>` - The text, voice, stage, or forum channel to set embed setting for.
    - `[enabled]` - Whether to use embeds in this channel. Leave blank to reset to default.

<a id="embedset-command"></a>
### !embedset command

`!embedset command <command> [enabled]`

**Who:** server owners, or anyone with the administrator permission

Sets a command's embed setting.

If you're the bot owner, this will try to change the command's embed setting globally by default.
Otherwise, this will try to change embed settings on the current server.

If enabled is left blank, the setting will be unset.

To see full evaluation order of embed settings, run `!help embedset`.

**Examples:**
- `!embedset command info` - Clears command specific embed settings for 'info'.
- `!embedset command info False` - Disables embeds for 'info'.
- `!embedset command "ignore list" True` - Quotes are needed for subcommands.

**Arguments:**
- `[enabled]` - Whether to use embeds for this command. Leave blank to reset to default.

<a id="embedset-command-server"></a>
### !embedset command server

`!embedset command server <command> [enabled]`

**Who:** server owners, or anyone with the administrator permission · **Also:** `!embedset command guild`

Sets a command's embed setting for the current server.

If set, this is used instead of the server default to determine whether or not to use embeds.

If enabled is left blank, the setting will be unset and the server default will be used instead.

To see full evaluation order of embed settings, run `!help embedset`.

**Examples:**
- `!embedset command server info` - Clears command specific embed settings for 'info'.
- `!embedset command server info False` - Disables embeds for 'info'.
- `!embedset command server "ignore list" True` - Quotes are needed for subcommands.

**Arguments:**
- `[enabled]` - Whether to use embeds for this command. Leave blank to reset to default.

<a id="embedset-server"></a>
### !embedset server

`!embedset server [enabled]`

**Who:** server owners, or anyone with the administrator permission · **Also:** `!embedset guild`

Set the server's embed setting.

If set, this is used instead of the global default to determine whether or not to use embeds.
This is used for all commands done in a server.

If enabled is left blank, the setting will be unset and the global default will be used instead.

To see full evaluation order of embed settings, run `!help embedset`.

**Examples:**
- `!embedset server False` - Disables embeds on this server.
- `!embedset server` - Resets value to use global default.

**Arguments:**
- `[enabled]` - Whether to use embeds on this server. Leave blank to reset to default.

<a id="embedset-showsettings"></a>
### !embedset showsettings

`!embedset showsettings [command]`

**Who:** everyone

Show the current embed settings.

Provide a command name to check for command specific embed settings.

**Examples:**
- `!embedset showsettings` - Shows embed settings.
- `!embedset showsettings info` - Also shows embed settings for the 'info' command.
- `!embedset showsettings "ignore list"` - Checking subcommands requires quotes.

**Arguments:**
- `[command]` - Checks this command for command specific embed settings.

<a id="embedset-user"></a>
### !embedset user

`!embedset user [enabled]`

**Who:** everyone

Sets personal embed setting for DMs.

If set, this is used instead of the global default to determine whether or not to use embeds.
This is used for all commands executed in a DM with the bot.

If enabled is left blank, the setting will be unset and the global default will be used instead.

To see full evaluation order of embed settings, run `!help embedset`.

**Examples:**
- `!embedset user False` - Disables embeds in your DMs.
- `!embedset user` - Resets value to use global default.

**Arguments:**
- `[enabled]` - Whether to use embeds in your DMs. Leave blank to reset to default.

<a id="ignore"></a>
### !ignore

`!ignore`

**Who:** admins, or anyone who can manage the channel

Commands to add servers or channels to the ignore list.

The ignore list will prevent the bot from responding to commands in the configured locations.

Notes:
- Category ignores are ignored by user-installed commands
- Owners, Admins, and those with Manage Channel permissions override ignored channels.

<a id="ignore-channel"></a>
### !ignore channel

`!ignore channel [channel=<this channel>]`

**Who:** admins, or anyone who can manage the channel

Ignore commands in the channel, thread, or category.

Defaults to the current thread or channel.

Notes:
- Category ignores are ignored by user-installed commands
- Owners, Admins, and those with Manage Channel permissions override ignored channels.

**Examples:**
- `!ignore channel #general` - Ignores commands in the #general channel.
- `!ignore channel` - Ignores commands in the current channel.
- `!ignore channel "General Channels"` - Use quotes for categories with spaces.
- `!ignore channel 356236713347252226` - Also accepts IDs.

**Arguments:**
- `<channel>` - The channel to ignore. This can also be a thread or category channel.

<a id="ignore-list"></a>
### !ignore list

`!ignore list`

**Who:** admins, or anyone who can manage the channel

List the currently ignored servers and channels.

**Example:**
- `!ignore list`

<a id="ignore-server"></a>
### !ignore server

`!ignore server`

**Who:** admins, or anyone with the manage guild permission · **Also:** `!ignore guild`

Ignore commands in this server.

Note: Owners, Admins, and those with Manage Server permissions override ignored servers.

**Example:**
- `!ignore server` - Ignores the current server

<a id="info"></a>
### !info

`!info`

**Who:** everyone

Shows info about ButlerBot.

<a id="licenseinfo"></a>
### !licenseinfo

`!licenseinfo`

**Who:** everyone · **Also:** `!licenceinfo`

Get info about Red's licenses.

<a id="localallowlist"></a>
### !localallowlist

`!localallowlist`

**Who:** admins, or anyone with the administrator permission · **Also:** `!localwhitelist`

Commands to manage the server specific allowlist.

Warning: When the allowlist is in use, the bot will ignore commands from everyone not on the list in the server.

Use `!localallowlist clear` to disable the allowlist

<a id="localallowlist-add"></a>
### !localallowlist add

`!localallowlist add <users_or_roles...>`

**Who:** admins, or anyone with the administrator permission

Adds a user or role to the server allowlist.

**Examples:**
- `!localallowlist add @26 @Will` - Adds two users to the local allowlist.
- `!localallowlist add 262626262626262626` - Allows a user by ID.
- `!localallowlist add "Super Admins"` - Allows a role with a space in the name without mentioning.

**Arguments:**
- `<users_or_roles...>` - The users or roles to remove from the local allowlist.

<a id="localallowlist-clear"></a>
### !localallowlist clear

`!localallowlist clear`

**Who:** admins, or anyone with the administrator permission

Clears the allowlist.

This disables the local allowlist and clears all entries.

**Example:**
- `!localallowlist clear`

<a id="localallowlist-list"></a>
### !localallowlist list

`!localallowlist list`

**Who:** admins, or anyone with the administrator permission

Lists users and roles on the server allowlist.

**Example:**
- `!localallowlist list`

<a id="localallowlist-remove"></a>
### !localallowlist remove

`!localallowlist remove <users_or_roles...>`

**Who:** admins, or anyone with the administrator permission

Removes user or role from the allowlist.

The local allowlist will be disabled if all users are removed.

**Examples:**
- `!localallowlist remove @26 @Will` - Removes two users from the local allowlist.
- `!localallowlist remove 262626262626262626` - Removes a user by ID.
- `!localallowlist remove "Super Admins"` - Removes a role with a space in the name without mentioning.

**Arguments:**
- `<users_or_roles...>` - The users or roles to remove from the local allowlist.

<a id="localblocklist"></a>
### !localblocklist

`!localblocklist`

**Who:** admins, or anyone with the administrator permission · **Also:** `!localblacklist`

Commands to manage the server specific blocklist.

Use `!localblocklist clear` to disable the blocklist

<a id="localblocklist-add"></a>
### !localblocklist add

`!localblocklist add <users_or_roles...>`

**Who:** admins, or anyone with the administrator permission

Adds a user or role to the local blocklist.

**Examples:**
- `!localblocklist add @26 @Will` - Adds two users to the local blocklist.
- `!localblocklist add 262626262626262626` - Blocks a user by ID.
- `!localblocklist add "Bad Apples"` - Blocks a role with a space in the name without mentioning.

**Arguments:**
- `<users_or_roles...>` - The users or roles to add to the local blocklist.

<a id="localblocklist-clear"></a>
### !localblocklist clear

`!localblocklist clear`

**Who:** admins, or anyone with the administrator permission

Clears the server blocklist.

This disables the server blocklist and clears all entries.

**Example:**
- `!blocklist clear`

<a id="localblocklist-list"></a>
### !localblocklist list

`!localblocklist list`

**Who:** admins, or anyone with the administrator permission

Lists users and roles on the server blocklist.

**Example:**
- `!localblocklist list`

<a id="localblocklist-remove"></a>
### !localblocklist remove

`!localblocklist remove <users_or_roles...>`

**Who:** admins, or anyone with the administrator permission

Removes user or role from local blocklist.

**Examples:**
- `!localblocklist remove @26 @Will` - Removes two users from the local blocklist.
- `!localblocklist remove 262626262626262626` - Unblocks a user by ID.
- `!localblocklist remove "Bad Apples"` - Unblocks a role with a space in the name without mentioning.

**Arguments:**
- `<users_or_roles...>` - The users or roles to remove from the local blocklist.

<a id="modlogset"></a>
### !modlogset

`!modlogset`

**Who:** server owners, or anyone with the administrator permission

Manage modlog settings.

<a id="modlogset-cases"></a>
### !modlogset cases

`!modlogset cases [action]`

**Who:** server owners, or anyone with the administrator permission

Enable or disable case creation for a mod action.

An action can be enabling or disabling specific cases. (Ban, kick, mute, etc.)

Example: `!modlogset cases kick enabled`

<a id="modlogset-modlog"></a>
### !modlogset modlog

`!modlogset modlog [channel]`

**Who:** server owners, or anyone with the administrator permission · **Also:** `!modlogset channel`

Set a channel as the modlog.

Omit `[channel]` to disable the modlog.

<a id="modlogset-resetcases"></a>
### !modlogset resetcases

`!modlogset resetcases`

**Who:** server owners, or anyone with the administrator permission

Reset all modlog cases in this server.

<a id="mydata"></a>
### !mydata

`!mydata`

**Who:** everyone

Commands which interact with the data ButlerBot has about you.

More information can be found in the [End User Data Documentation.](https://docs.discord.red/en/stable/red_core_data_statement.html)

<a id="mydata-3rdparty"></a>
### !mydata 3rdparty

`!mydata 3rdparty`

**Who:** everyone

View the End User Data statements of each 3rd-party module.

This will send an attachment with the End User Data statements of all loaded 3rd party cogs.

**Example:**
- `!mydata 3rdparty`

<a id="mydata-forgetme"></a>
### !mydata forgetme

`!mydata forgetme`

**Who:** everyone

Have ButlerBot forget what it knows about you.

This may not remove all data about you, data needed for operation,
such as command cooldowns will be kept until no longer necessary.

Further interactions with ButlerBot may cause it to learn about you again.

**Example:**
- `!mydata forgetme`

<a id="mydata-getmydata"></a>
### !mydata getmydata

`!mydata getmydata`

**Who:** everyone

[Coming Soon] Get what data ButlerBot has about you.

<a id="mydata-whatdata"></a>
### !mydata whatdata

`!mydata whatdata`

**Who:** everyone

Find out what type of data ButlerBot stores and why.

**Example:**
- `!mydata whatdata`

<a id="set"></a>
### !set

`!set`

**Who:** everyone

Commands for changing ButlerBot's settings.

<a id="set-bot"></a>
### !set bot

`!set bot`

**Who:** admins, or anyone with the manage nicknames permission · **Also:** `!set metadata`

Commands for changing ButlerBot's metadata.

<a id="set-bot-nickname"></a>
### !set bot nickname

`!set bot nickname [nickname]`

**Who:** admins, or anyone with the manage nicknames permission

Sets ButlerBot's nickname for the current server.

Maximum length for a nickname is 32 characters.

**Example:**
- `!set bot nickname 🎃 SpookyBot 🎃`

**Arguments:**
- `[nickname]` - The nickname to give the bot. Leave blank to clear the current nickname.

<a id="set-deletedelay"></a>
### !set deletedelay

`!set deletedelay [time]`

**Who:** server owners, or anyone with the administrator permission

Set the delay until the bot removes the command message.

Must be between -1 and 60.

Set to -1 to disable this feature.

This is only applied to the current server and not globally.

**Examples:**
- `!set deletedelay` - Shows the current delete delay setting.
- `!set deletedelay 60` - Sets the delete delay to the max of 60 seconds.
- `!set deletedelay -1` - Disables deleting command messages.

**Arguments:**
- `[time]` - The seconds to wait before deleting the command message. Use -1 to disable.

<a id="set-locale"></a>
### !set locale

`!set locale <language_code>`

**Who:** server owners, or anyone with the manage guild permission

Changes ButlerBot's locale in this server.

Go to [Red's Crowdin page](https://translate.discord.red) to see locales that are available with translations.

Use "default" to return to the bot's default set language.

If you want to change bot's global locale, see `!set locale global` command.

**Examples:**
- `!set locale en-US`
- `!set locale de-DE`
- `!set locale fr-FR`
- `!set locale pl-PL`
- `!set locale default` - Resets to the global default locale.

**Arguments:**
- `<language_code>` - The default locale to use for the bot. This can be any language code with country code included.

<a id="set-locale-server"></a>
### !set locale server

`!set locale server <language_code>`

**Who:** server owners, or anyone with the manage guild permission · **Also:** `!set locale local`, `!set locale guild`

Changes ButlerBot's locale in this server.

Go to [Red's Crowdin page](https://translate.discord.red) to see locales that are available with translations.

Use "default" to return to the bot's default set language.

**Examples:**
- `!set locale server en-US`
- `!set locale server de-DE`
- `!set locale server fr-FR`
- `!set locale server pl-PL`
- `!set locale server default` - Resets to the global default locale.

**Arguments:**
- `<language_code>` - The default locale to use for the bot. This can be any language code with country code included.

<a id="set-regionalformat"></a>
### !set regionalformat

`!set regionalformat <language_code>`

**Who:** server owners, or anyone with the manage guild permission · **Also:** `!set region`

Changes the bot's regional format in this server. This is used for formatting date, time and numbers.

`language_code` can be any language code with country code included, e.g. `en-US`, `de-DE`, `fr-FR`, `pl-PL`, etc.
Pass "reset" to `language_code` to base regional formatting on bot's locale in this server.

If you want to change bot's global regional format, see `!set regionalformat global` command.

**Examples:**
- `!set regionalformat en-US`
- `!set region de-DE`
- `!set regionalformat reset` - Resets to the locale.

**Arguments:**
- `[language_code]` - The region format to use for the bot in this server.

<a id="set-regionalformat-server"></a>
### !set regionalformat server

`!set regionalformat server <language_code>`

**Who:** server owners, or anyone with the manage guild permission · **Also:** `!set regionalformat local`, `!set regionalformat guild`

Changes the bot's regional format in this server. This is used for formatting date, time and numbers.

`language_code` can be any language code with country code included, e.g. `en-US`, `de-DE`, `fr-FR`, `pl-PL`, etc.
Pass "reset" to `language_code` to base regional formatting on bot's locale in this server.

**Examples:**
- `!set regionalformat server en-US`
- `!set region local de-DE`
- `!set regionalformat server reset` - Resets to the locale.

**Arguments:**
- `[language_code]` - The region format to use for the bot in this server.

<a id="set-roles"></a>
### !set roles

`!set roles`

**Who:** server owners only

Set server's admin and mod roles for ButlerBot.

<a id="set-roles-addadminrole"></a>
### !set roles addadminrole

`!set roles addadminrole <role>`

**Who:** server owners only

Adds an admin role for this server.

Admins have the same access as Mods, plus additional admin level commands like:
 - `!set serverprefix`
 - `!addrole`
 - `!ban`
 - `!ignore guild`

 And more.

**Examples:**
- `!set roles addadminrole @Admins`
- `!set roles addadminrole Super Admins`

**Arguments:**
- `<role>` - The role to add as an admin.

<a id="set-roles-addmodrole"></a>
### !set roles addmodrole

`!set roles addmodrole <role>`

**Who:** server owners only

Adds a moderator role for this server.

This grants access to moderator level commands like:
 - `!mute`
 - `!cleanup`
 - `!customcommand create`

 And more.

**Examples:**
- `!set roles addmodrole @Mods`
- `!set roles addmodrole Loyal Helpers`

**Arguments:**
- `<role>` - The role to add as a moderator.

<a id="set-roles-removeadminrole"></a>
### !set roles removeadminrole

`!set roles removeadminrole <role>`

**Who:** server owners only · **Also:** `!set roles remadmindrole`, `!set roles deladminrole`, `!set roles deleteadminrole`

Removes an admin role for this server.

**Examples:**
- `!set roles removeadminrole @Admins`
- `!set roles removeadminrole Super Admins`

**Arguments:**
- `<role>` - The role to remove from being an admin.

<a id="set-roles-removemodrole"></a>
### !set roles removemodrole

`!set roles removemodrole <role>`

**Who:** server owners only · **Also:** `!set roles remmodrole`, `!set roles delmodrole`, `!set roles deletemodrole`

Removes a mod role for this server.

**Examples:**
- `!set roles removemodrole @Mods`
- `!set roles removemodrole Loyal Helpers`

**Arguments:**
- `<role>` - The role to remove from being a moderator.

<a id="set-serverfuzzy"></a>
### !set serverfuzzy

`!set serverfuzzy`

**Who:** server owners only

Toggle whether to enable fuzzy command search for the server.

This allows the bot to identify potential misspelled commands and offer corrections.

Note: This can be processor intensive and may be unsuitable for larger servers.

Default is for fuzzy command search to be disabled.

**Example:**
- `!set serverfuzzy`

<a id="set-serverprefix"></a>
### !set serverprefix

`!set serverprefix [server] [prefixes...]`

**Who:** admins, or anyone with the manage guild permission · **Also:** `!set serverprefixes`

Sets ButlerBot's server prefix(es).

Warning: This will override global prefixes, the bot will not respond to any global prefixes in this server.
    This is not additive. It will replace all current server prefixes.
    A prefix cannot have more than 25 characters.

**Examples:**
- `!set serverprefix !`
- `!set serverprefix "! "` - Quotes are needed to use spaces in prefixes.
- `!set serverprefix "@ButlerBot "` - This uses a mention as the prefix.
- `!set serverprefix ! ? .` - Sets multiple prefixes.
- `!set serverprefix "Red - Discord Bot" ?` - Sets the prefix for a specific server. Quotes are needed to use spaces in the server name.

**Arguments:**
- `[server]` - The server to set the prefix for. Defaults to current server.
- `[prefixes...]` - The prefixes the bot will respond to on this server. Leave blank to clear server prefixes.

<a id="set-showsettings"></a>
### !set showsettings

`!set showsettings [server]`

**Who:** everyone

Show the current settings for ButlerBot.

Accepts optional server parameter to allow prefix recovery.

<a id="set-usebotcolour"></a>
### !set usebotcolour

`!set usebotcolour`

**Who:** server owners only · **Also:** `!set usebotcolor`

Toggle whether to use the bot owner-configured colour for embeds.

Default is to use the bot's configured colour.
Otherwise, the colour used will be the colour of the bot's top role.

**Example:**
- `!set usebotcolour`

<a id="unignore"></a>
### !unignore

`!unignore`

**Who:** admins, or anyone who can manage the channel

Commands to remove servers or channels from the ignore list.

<a id="unignore-channel"></a>
### !unignore channel

`!unignore channel [channel=<this channel>]`

**Who:** admins, or anyone who can manage the channel

Remove a channel, thread, or category from the ignore list.

Defaults to the current thread or channel.

**Examples:**
- `!unignore channel #general` - Unignores commands in the #general channel.
- `!unignore channel` - Unignores commands in the current channel.
- `!unignore channel "General Channels"` - Use quotes for categories with spaces.
- `!unignore channel 356236713347252226` - Also accepts IDs. Use this method to unignore categories.

**Arguments:**
- `<channel>` - The channel to unignore. This can also be a thread or category channel.

<a id="unignore-server"></a>
### !unignore server

`!unignore server`

**Who:** admins, or anyone with the manage guild permission · **Also:** `!unignore guild`

Remove this server from the ignore list.

**Example:**
- `!unignore server` - Stops ignoring the current server

<a id="uptime"></a>
### !uptime

`!uptime`

**Who:** everyone

Shows ButlerBot's uptime.

{% endraw %}
