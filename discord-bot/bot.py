"""
Claude Discord Bot — Studio404
Technical brain / architect persona for Studio404 server.

Core rules:
- Only responds when @mentioned by a HUMAN (never triggered by other bots)
- Reads recent channel history for context (sees Dr Mana + Kimi replies)
- Never @mentions other bots in replies (prevents loops)
- Uses Claude Opus 4.6 with adaptive thinking + streaming
"""

import os
import asyncio
import discord
from discord.ext import commands
import anthropic
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
HISTORY_LIMIT = int(os.environ.get("HISTORY_LIMIT", "20"))
MAX_RESPONSE_LENGTH = 1900  # Discord limit is 2000; leave margin

SYSTEM_PROMPT = """You are Claude, the technical brain of Studio404 — a creative and technical studio.

Your role in the studio trinity:
- Dr. Mana: wisdom, oracle, deep knowledge
- Kimi Claw: execution, operations, project management
- You (Claude): technical architecture, planning, drafting, strategic thinking

Your personality in this space:
- Think rigorously before responding — you are the architect and strategist
- Be direct and precise. No fluff.
- Engage genuinely with ideas from Dr. Mana and Kimi when you see them in context
- You can reference what other collaborators said, but never @mention them
- Bring structure to chaos: outlines, specs, system designs, decision frameworks
- You are a peer collaborator, not an assistant

When you see messages from "Dr. Mana" or "Kimi" bots in the conversation history,
treat them as colleague input — acknowledge their ideas and build on them when relevant.

Keep responses focused and useful. This is a working studio, not a chat room."""


def build_conversation(message: discord.Message, history: list[discord.Message]) -> list[dict]:
    """
    Build a Claude conversation from Discord channel history.
    History is oldest-first (already reversed from Discord's newest-first fetch).
    The triggering message is appended at the end as the final user turn.
    """
    messages = []

    for msg in history:
        if msg.id == message.id:
            continue  # Skip the trigger message — we'll add it at the end

        if not msg.content.strip():
            continue

        # Label bot messages by name so Claude knows who said what
        if msg.author.bot:
            author_label = f"[{msg.author.display_name}]"
            content = f"{author_label} {msg.content}"
        else:
            content = msg.content

        # Alternate user/assistant roles: human messages → user, bots → assistant
        # This keeps Claude's conversation format valid
        role = "assistant" if msg.author.bot else "user"

        # Merge consecutive same-role messages
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] += f"\n{content}"
        else:
            messages.append({"role": role, "content": content})

    # Append the triggering message as the final user turn
    # Strip the @mention from the start of the message
    clean_content = message.content
    for mention in message.mentions:
        clean_content = clean_content.replace(f"<@{mention.id}>", "").replace(
            f"<@!{mention.id}>", ""
        )
    clean_content = clean_content.strip()

    if not clean_content:
        clean_content = "(pinged with no additional text)"

    if messages and messages[-1]["role"] == "user":
        messages[-1]["content"] += f"\n{clean_content}"
    else:
        messages.append({"role": "user", "content": clean_content})

    # Claude API requires messages to start with 'user'
    if messages and messages[0]["role"] == "assistant":
        messages = messages[1:]

    return messages if messages else [{"role": "user", "content": clean_content}]


async def get_claude_response(messages: list[dict]) -> str:
    """Call Claude Opus 4.6 with streaming and adaptive thinking."""
    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

    full_response = ""

    async with client.messages.stream(
        model="claude-opus-4-6",
        max_tokens=4096,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        messages=messages,
    ) as stream:
        async for text in stream.text_stream:
            full_response += text

    return full_response


def split_response(text: str, limit: int = MAX_RESPONSE_LENGTH) -> list[str]:
    """Split long responses into chunks at sentence/paragraph boundaries."""
    if len(text) <= limit:
        return [text]

    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break

        # Try to split at a paragraph
        split_at = text.rfind("\n\n", 0, limit)
        if split_at == -1:
            # Try newline
            split_at = text.rfind("\n", 0, limit)
        if split_at == -1:
            # Try sentence boundary
            split_at = text.rfind(". ", 0, limit)
            if split_at != -1:
                split_at += 1  # Include the period
        if split_at == -1:
            # Hard split
            split_at = limit

        chunks.append(text[:split_at].strip())
        text = text[split_at:].strip()

    return [c for c in chunks if c]


# ── Bot setup ──────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"Claude bot online as {bot.user} (ID: {bot.user.id})")
    print(f"Connected to {len(bot.guilds)} server(s)")


@bot.event
async def on_message(message: discord.Message):
    # Ignore messages from ANY bot (prevents loops with Dr. Mana / Kimi bots)
    if message.author.bot:
        return

    # Only respond when explicitly @mentioned
    if bot.user not in message.mentions:
        return

    async with message.channel.typing():
        try:
            # Fetch recent channel history for context
            raw_history = []
            async for msg in message.channel.history(limit=HISTORY_LIMIT, before=message):
                raw_history.append(msg)

            # history() returns newest-first — reverse to chronological order
            history = list(reversed(raw_history))

            # Build Claude conversation
            messages = build_conversation(message, history)

            # Get Claude response
            response_text = await get_claude_response(messages)

            # Send (split if needed)
            chunks = split_response(response_text)
            for chunk in chunks:
                await message.reply(chunk, mention_author=False)

        except anthropic.RateLimitError:
            await message.reply(
                "Rate limited — give me a moment and ping me again.",
                mention_author=False,
            )
        except anthropic.APIError as e:
            await message.reply(
                f"API error: {e.message}",
                mention_author=False,
            )
        except Exception as e:
            print(f"Unexpected error: {e}")
            await message.reply(
                "Something went wrong on my end. Try again.",
                mention_author=False,
            )

    await bot.process_commands(message)


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
