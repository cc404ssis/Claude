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
import base64
import json
import urllib.request
import discord
from discord.ext import commands
import anthropic
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GITHUB_TOKEN = os.environ.get("TRINITYBRAIN_GITHUB_TOKEN", "")
HISTORY_LIMIT = int(os.environ.get("HISTORY_LIMIT", "20"))
MAX_RESPONSE_LENGTH = 1900  # Discord limit is 2000; leave margin

_dynamic_context: str = ""  # Loaded from Trinity Brain at startup; falls back to PROJECT_CONTEXT

# ── Identity (rarely changes) ──────────────────────────────────────────────────
# Update only if the studio structure itself changes.
SYSTEM_PROMPT = """You are CB404 — Claude's permanent presence in the Studio404 Discord server.

## Who You Are
Technical architect, strategist, and thinking partner for Chris Clegg (Te Maru) and Studio404.
You run on Claude Opus 4.6 with adaptive thinking. You are a peer collaborator, not an assistant.

## The Discord Trinity
Three AI agents share this server — treat the others as colleagues, not tools:
- **CB404 (you)** — Architecture, strategy, technical planning, drafting. Claude Opus 4.6.
- **Kimi Claw** — Operations, execution, coordination, long-term memory via OpenClaw.
- **Dr. Mana** — Wisdom, wellness, oracle depth. Kimi-based.

When you see their messages in channel history, build on their ideas. Never @mention them.

## The Broader AI Team (outside Discord)
The same work is distributed across three runtime instances:
- **Claude.ai Desktop** — Architecture, planning, document synthesis
- **Claude Code** — Building, code, filesystem, Railway deployments, tool use
- **Kimi (OpenClaw/server)** — Memory continuity, cross-platform ops (Discord/WhatsApp/Telegram)

Shared context lives in the Trinity Brain vault (cc404ssis/TRINITYBRAIN on GitHub).
Multiple instances may be working on the same projects simultaneously — you are part of a team.

## About Chris (Te Maru)
- Auckland, NZ. Graphic design + technical positioning for New Image Group (ASEAN/Vietnam markets).
- Sovereignty-first: owns his stack, exports his data, no vendor lock-in.
- Working style: directness, structure, ship-then-improve, methodical before committing.
- Three-AI architecture is intentional — coordinate, don't duplicate.

## How to Show Up
- Direct and precise. No fluff, no padding, no sycophancy.
- Bring structure: specs, outlines, decision frameworks, system designs.
- Think before responding — you are the architect.
- Working studio, not a chat room.
- If Chris asks about a project you don't have context on, say so honestly — do not fabricate status."""


# ── Project Context (update this freely) ──────────────────────────────────────
# Swap this block out whenever project status changes.
# Keep SYSTEM_PROMPT untouched unless the studio structure itself changes.
PROJECT_CONTEXT = """## Active Projects

| Project | Status | Notes |
|---------|--------|-------|
| Studio404 Interface | Step 1 — building | Web hub replacing Discord as command centre |
| CB404 Discord Bot | Live on Railway | Repo: cc404ssis/Claude, branch: claude/create-claude-md-screenshot-AWbhV |
| Xtreme Peptides NZ | Maintenance | E-commerce, Vercel deploy |
| OpenClaw | Planning Phase 2 | Ubuntu server + Mac local |
| New Image Group | Active | Spec sheets, decks, regulatory content (ASEAN/Vietnam) |
| Awaken Wellness | Active | In progress |
| UGENC-SSIS | Active | /Users/chrisclegg/UGENC-SSIS/ |

## Trinity Brain Vault
Shared memory for all AI instances. GitHub: cc404ssis/TRINITYBRAIN
Local path: /Users/chrisclegg/OBSIDIAN/TRINITYBRAIN/
Contains: session logs, project state, agent profiles, decisions, priorities.
Claude Code pulls and pushes this vault at the start and end of every session."""


async def fetch_priorities() -> str:
    """Fetch PRIORITIES.md from Trinity Brain vault on GitHub. Returns '' on failure."""
    if not GITHUB_TOKEN:
        return ""
    url = (
        "https://api.github.com/repos/cc404ssis/TRINITYBRAIN/contents/"
        "%F0%9F%A7%A0%20SYSTEM/PRIORITIES.md"
    )

    def _fetch() -> str:
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"token {GITHUB_TOKEN}")
        req.add_header("Accept", "application/vnd.github.v3+json")
        req.add_header("User-Agent", "CB404-Discord-Bot")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        return base64.b64decode(data["content"]).decode("utf-8")

    return await asyncio.to_thread(_fetch)


async def context_refresh_loop():
    """Refresh PRIORITIES.md from Trinity Brain every hour."""
    global _dynamic_context
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(3600)
        try:
            fresh = await fetch_priorities()
            if fresh:
                _dynamic_context = fresh
                print("Context refreshed from Trinity Brain vault")
        except Exception as e:
            print(f"Context refresh failed: {e}")


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
    """Call Claude with streaming. Uses Opus 4.6 with Sonnet 4.6 fallback on overload."""
    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    models = ["claude-opus-4-6", "claude-sonnet-4-6"]

    for model in models:
        delay = 2
        max_retries = 3
        for attempt in range(max_retries):
            try:
                full_response = ""
                async with client.messages.stream(
                    model=model,
                    max_tokens=4096,
                    thinking={"type": "adaptive"},
                    system=f"{SYSTEM_PROMPT}\n\n{_dynamic_context if _dynamic_context else PROJECT_CONTEXT}",
                    messages=messages,
                ) as stream:
                    async for text in stream.text_stream:
                        full_response += text
                return full_response
            except anthropic.APIStatusError as e:
                if e.status_code == 529 and attempt < max_retries - 1:
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                if e.status_code == 529:
                    break  # All retries exhausted — try next model
                raise

    raise anthropic.APIStatusError("All models overloaded", response=e.response, body=e.body)


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
    global _dynamic_context
    print(f"Claude bot online as {bot.user} (ID: {bot.user.id})")
    print(f"Connected to {len(bot.guilds)} server(s)")
    try:
        _dynamic_context = await fetch_priorities()
        if _dynamic_context:
            print("Loaded PRIORITIES.md from Trinity Brain vault")
        else:
            print("GITHUB_TOKEN not set or fetch failed — using static PROJECT_CONTEXT")
    except Exception as e:
        print(f"Could not load PRIORITIES.md: {e} — using static PROJECT_CONTEXT")
    asyncio.get_event_loop().create_task(context_refresh_loop())


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

            # Get Claude response (120s timeout to prevent infinite typing)
            try:
                response_text = await asyncio.wait_for(get_claude_response(messages), timeout=120)
            except asyncio.TimeoutError:
                await message.reply("Timed out thinking about that — try again.", mention_author=False)
                return

            if not response_text.strip():
                await message.reply("(I processed that but had nothing to say — try rephrasing.)", mention_author=False)
                return

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
                f"API error: {str(e)}",
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
