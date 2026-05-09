# YapHub

YapHub is a lightweight Discord bot that creates temporary voice channels when users join a lobby channel, then cleans those channels up automatically when they are empty.

## MVP Scope

- Create a `➕ Join to Yap` lobby channel with `/yap setup`
- Auto-create a temporary voice channel when a user joins the lobby
- Move the user into their new yap room
- Track temporary channel ownership in memory
- Delete empty temporary yap rooms automatically
- Support basic owner controls:
  - `/yap lock`
  - `/yap unlock`
  - `/yap limit`
  - `/yap rename`
  - `/yap claim`

## Local Setup

1. Create a Discord application and bot in the Discord Developer Portal.
2. Enable the required bot permissions:
   - Manage Channels
   - Move Members
   - View Channels
   - Connect
   - Speak
3. Copy `.env.example` to `.env`.
4. Add your bot token.
5. Install dependencies:

```bash
pip install -r requirements.txt
```

6. Run the bot:

```bash
python bot.py
```

## Environment Variables

```env
DISCORD_TOKEN=your_discord_bot_token_here
```

## Notes

This MVP stores setup and temp-channel state in memory. Restarting the bot clears runtime state. Persistence can be added later with SQLite or Postgres once the core flow is stable.
