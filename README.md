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

## How Server Owners Add YapHub

YapHub must be running from one hosted bot account before other people can add it to their servers. Server owners do not run their own copy unless they are self-hosting.

### 1. Create the Invite Link

In the Discord Developer Portal:

1. Open the YapHub application.
2. Go to **OAuth2 → URL Generator**.
3. Select scopes:
   - `bot`
   - `applications.commands`
4. Select bot permissions:
   - Manage Channels
   - Move Members
   - View Channels
   - Connect
   - Speak
5. Copy the generated URL.

### 2. Add YapHub to a Server

The server owner/admin opens the invite URL, picks their server, and approves the requested permissions.

They need permission to add bots to that server.

### 3. Configure the Voice Lobby

Inside Discord, run:

```text
/yap setup
```

YapHub creates:

```text
➕ Join to Yap
```

When someone joins that lobby, YapHub creates a temporary voice channel and moves them into it.

### 4. Current MVP Behavior

```text
User joins ➕ Join to Yap
→ YapHub creates 🗣️ User's Yap
→ YapHub moves the user into the temp channel
→ YapHub deletes the temp channel when empty
```

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
