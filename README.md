# Greed Live Roster Bot

Read-only Discord bot generating a live guild roster grouped by **Class → Combat Role → Guild Rank**.

## Setup

1. Install Python 3.11 or newer.
2. In the [Discord Developer Portal](https://discord.com/developers/applications), create an application and copy its bot token.
3. Under **Bot**, enable **Server Members Intent**. No Message Content Intent is required.
4. Under **Installation**, enable Guild Install with `bot` and `applications.commands` scopes. Select these permissions: View Channels, Send Messages, Embed Links, Read Message History. Install into your server.
5. Create a private text channel such as `#guild-roster`. Deny `View Channel` to `@everyone`, allow it for your officer role and the bot. Deny `Send Messages` to regular members. The bot needs View Channel, Send Messages, Embed Links, and Read Message History in this channel.
6. In Discord, enable **User Settings → Advanced → Developer Mode**. Right-click your server → Copy Server ID. Right-click the roster channel → Copy Channel ID.
7. Copy `.env.example` to `.env` and set `DISCORD_TOKEN`, `GUILD_ID`, and `ROSTER_CHANNEL_ID`.
8. Edit `config.json` to match the **exact names** of your existing class, combat, and rank roles. Included names are examples, not confirmed server configuration. `Trial` is an alias for Recruit until changed.
9. In a terminal opened in this folder, run:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python bot.py
```

The bot creates and edits one consolidated roster embed in the configured channel for normal guild sizes. On startup it automatically removes surplus old roster messages tracked in `roster_state.json`. Manage Server users can run `/roster_refresh`.

## Notes

- This bot **does not** assign or modify member roles, permissions, or channels.
- Only members with **exactly one** mapped rank (Raider, Recruit, Social), class, and combat role appear in classified groups. Issues appear in a separate section.
- Members with no mapped guild rank are excluded entirely, including from Needs Attention.
- Normally only one roster message is displayed. Very large rosters may require additional messages because Discord limits embed size. On restart, the bot updates messages recorded in `roster_state.json`; preserve that file when moving hosts to avoid duplicate roster posts.
- Avoid running two copies of the bot at once.
- To change channel visibility later, adjust Discord channel permissions, not the Python code.
- Only `GUILD_MEMBERS` privileged intent is necessary, and the bot fetches membership on startup and full updates.
- Long class sections are split into multiple fields and, if required by Discord limits, additional roster messages.

## Files

- `bot.py`: main bot.
- `config.json`: Discord role-name mappings.
- `.env`: private credentials and IDs (create this yourself, never share it).
- `roster_state.json`: created by bot to track its existing messages.

### Roster emojis
The panel uses Unicode emojis for classes, combat roles, and guild ranks. Discord renders these without custom server emoji permissions. To change them, edit `class_icons`, `combat_icons`, or `rank_icons` in `make_pages()` within `bot.py`. Official WoW class icons would require custom Discord emoji assets instead.
