---
title: Translation
nav_order: 10
permalink: /translate/
---

# Translation

ButlerBot translates messages with Google Translate.

## Set your language once

```
!setmylanguage spanish
```

`/setmylanguage` works too. Your language is saved everywhere the bot is; the default is English. You can use names or codes: `korean` or `ko`, `chinese` or `zh`.

## Translating

| How | What happens |
|---|---|
| Right-click a message → **Apps** → **Translate** | Translates it into your language. **Only you** see the result. |
| Reply to a message with `!translate` | Posts the translation into your language as a reply. |
| `!translate <text>` | Translates your text into your language. |
| `!translate to <language> <text>` | Translates into a specific language, e.g. `!translate to japanese good game!` (also works as a reply). |
| `/translate to:<language> text:<text>` | The slash version, with language suggestions as you type. |

The result shows the detected source language → the target.

{: .note }
> Translation only works in regular text channels, not in threads, forum posts or voice-channel chats. To translate something from a thread, copy the text and use `!translate` in a regular channel.
