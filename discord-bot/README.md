# Claude Bot — Studio404

The technical brain / architect of Studio404. Collaborates with Dr. Mana and Kimi Claw.

## Loop Prevention

**Core rule: bots only fire when a human @mentions them.**

```
You @ClaudeBot @KimiBot  "here's the project brief..."
  → Claude reads message + channel history → replies
  → Kimi reads message + channel history → replies
  → Both can see each other's replies in next round's history
  → Neither bot @mentions the other → no trigger → silence
  → You ping again → cycle repeats
```

## Setup

### 1. Create the Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. New Application → name it (e.g. "Claude / CC404")
3. Bot tab → Add Bot → copy the **Token**
4. Under Privileged Gateway Intents, enable:
   - **Message Content Intent**
   - **Server Members Intent** (optional, for display names)
5. OAuth2 → URL Generator:
   - Scopes: `bot`
   - Bot Permissions: `Send Messages`, `Read Message History`, `Read Messages/View Channels`
6. Copy the generated URL → open in browser → add to Studio404

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your tokens
```

### 3. Install & Run

```bash
pip install -r requirements.txt
python bot.py
```

### 4. Production (keep it running)

Use `screen`, `tmux`, or a systemd service:

```bash
# With screen
screen -S claude-bot
python bot.py
# Ctrl+A, D to detach
```

Or run on a VPS / Raspberry Pi for 24/7 uptime.

## Environment Variables

| Variable | Description |
|---|---|
| `DISCORD_BOT_TOKEN` | From Discord Developer Portal |
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `HISTORY_LIMIT` | Messages of context to read (default: 20) |

## How Context Works

When you @mention Claude, the bot:
1. Fetches the last 20 messages in the channel
2. Passes them as conversation history to Claude
3. Claude sees what Dr. Mana and Kimi said and can build on it
4. Replies with its response, no @mentions to other bots

Claude knows Dr. Mana and Kimi by their bot display names in the history.
