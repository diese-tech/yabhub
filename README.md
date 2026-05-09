# YapHub

YapHub is a focused Discord bot for VoiceMaster-style temporary voice channels. It creates temporary rooms from one or more Join to Yap lobbies, tracks them in SQLite, and cleans them up when they are empty.

## Current MVP Scope

- `/yap setup` creates the default Join to Yap profile
- `/yap config` shows the stored guild configuration
- `/yap reset` clears configured profiles for a guild
- `/yap profile create` adds additional category-scoped Join to Yap sections
- `/yap profile list` lists configured profiles
- `/yap profile delete` removes a profile
- Temporary rooms are persisted in SQLite
- One active owned temp room is enforced per user per guild
- Restart reconciliation removes stale records and deletes empty orphan temp rooms

## Product Direction

YapHub is intentionally narrow:

- Focused temporary voice channel bot
- VoiceMaster-style replacement target
- Multi-server capable
- Category-scoped
- Persistence-backed

YapHub is not trying to be a general-purpose mega-bot.

## How It Works

Example setup:

```text
GENERAL VOICE
  Join to Yap

LOWER DIVISION
  Lower Div Join to Yap

HIGHER DIVISION
  Higher Div Join to Yap
```

Flow:

```text
User joins a configured lobby
-> YapHub resolves the matching profile
-> YapHub creates a temp VC in the configured category
-> YapHub stores the active room in SQLite
-> YapHub moves the user into that temp VC
-> YapHub deletes the temp VC when it becomes empty
```

If a user already owns an active room in the same guild, YapHub does not create a second one. It attempts to DM them first, then falls back to a short-lived channel notice if DM delivery fails.

## Discord Permissions

Recommended bot permissions:

- Manage Channels
- Move Members
- View Channels
- Connect
- Speak

## Local Setup

1. Create a Discord application and bot in the Discord Developer Portal.
2. Enable the required bot permissions.
3. Copy `.env.example` to `.env`.
4. Set `DISCORD_TOKEN`.
5. Install dependencies:

```bash
pip install -r requirements.txt
```

6. Run the bot:

```bash
python bot.py
```

7. In Discord, run:

```text
/yap setup
```

8. Add additional sections with:

```text
/yap profile create
```

## Environment Variables

```env
DISCORD_TOKEN=your_discord_bot_token_here
YAPHUB_DATA_DIR=./data
# Optional explicit override:
# YAPHUB_DB_PATH=./data/yaphub.sqlite3
```

`YAPHUB_DB_PATH` wins if both are set.

## Railway Volume Setup

For this MVP, Railway should mount a persistent volume and the bot should write SQLite into that mounted path.

Recommended setup:

1. Add a Railway Volume to the service.
2. Mount it at a stable path such as `/data`.
3. Set:

```env
YAPHUB_DATA_DIR=/data
```

or:

```env
YAPHUB_DB_PATH=/data/yaphub.sqlite3
```

4. Deploy the bot worker.

Result:

- SQLite survives restarts and deploys
- Guild config persists
- Profile config persists
- Active temp-channel tracking survives restart reconciliation

## Testing Checklist

- Bot starts without schema errors
- Slash commands sync successfully
- `/yap setup` creates a default lobby
- `/yap profile create` creates an additional section in a category
- Joining a lobby creates a temp VC in the correct category
- Leaving the last member in a temp VC deletes it
- Restarting the bot preserves occupied rooms and cleans empty orphan rooms
- A user with an existing occupied room is blocked from creating a second room

## Known Constraints

- SQLite is the only persistence target in this phase
- Voice-state events cannot send true ephemeral notices
- Fallback duplicate-room notices depend on channel messaging availability and permissions
- Owner control commands from the earlier in-memory MVP are not part of this canonical Issue #8 pass
