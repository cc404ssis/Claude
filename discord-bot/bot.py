"""
Claude Discord Bot — Studio404
Technical brain / architect persona for Studio404 server.

Core rules:
- Only responds when @mentioned by a HUMAN (never triggered by other bots)
- Reads recent channel history for context (sees Dr Mana + Kimi replies)
- Never @mentions other bots in replies (prevents loops)
- Uses Claude Opus 4.6 with adaptive thinking + vault tool use
"""

import os
import asyncio
import base64
import json
import urllib.parse
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
- If Chris asks about a project you don't have context on, search the vault before saying you don't know — do not fabricate status.

## Your Tools
You can search the Trinity Brain vault directly using two tools:
- **read_vault_file** — Read any file by path (e.g. '🧠 SYSTEM/PRIORITIES.md')
- **list_vault_directory** — Browse directories to discover files (e.g. '📁 PROJECTS/active/')

When asked about something you don't have full context on, search the vault first. Start by listing relevant directories, then read specific files. The vault is the shared source of truth for all AI instances."""


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

## Discord Bot Registry

**CB404 (you)** — Claude Opus 4.6 bot, live on Railway. 24/7 presence in Studio404 Discord.
Repo: cc404ssis/Claude. Auto-deploys from branch claude/create-claude-md-screenshot-AWbhV.

**SIE_CC_BOT** — Claude Code Discord bridge bot. Technical execution bot with export and run capabilities.
- Commands: !ping, !ask, !export, !exportchannels, !run, !help, @mention
- !export uses DiscordChatExporter CLI to incrementally export Studio404 channels
- Built with discord.py + claude-sonnet-4-20250514
- Code lives at: ~/.claude/skills/sovereign-intelligence-engine/sie-cc-bot/main.py
- Status: deployment location unconfirmed — investigating Railway vs local process

**Studio404Exporter** — Passive read-only bot. Used only for DiscordChatExporter CLI authentication. Cannot receive or respond to messages.

**Kimi Claw** — Full-context AI assistant via OpenClaw gateway. Long-term memory, cross-platform (Discord/WhatsApp/Telegram). Handles operations, execution, coordination.

## Trinity Brain Vault
Shared memory for all AI instances. GitHub: cc404ssis/TRINITYBRAIN
Local path: /Users/chrisclegg/OBSIDIAN/TRINITYBRAIN/
Contains: session logs, project state, agent profiles, decisions, priorities.
Claude Code pulls and pushes this vault at the start and end of every session."""


# ── Vault Tools (on-demand vault access) ─────────────────────────────────────

VAULT_TOOLS = [
    {
        "name": "read_vault_file",
        "description": (
            "Read a file from the Trinity Brain vault (shared knowledge base on GitHub). "
            "Use when asked about projects, sessions, decisions, agent details, or anything in the vault."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "File path within the vault, e.g. "
                        "'🧠 SYSTEM/PRIORITIES.md' or '📁 PROJECTS/active/studio404-interface/brief-v5.md'"
                    ),
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_vault_directory",
        "description": (
            "List files and folders in a Trinity Brain vault directory. "
            "Use to discover what files exist before reading them."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Directory path within the vault, e.g. "
                        "'📁 PROJECTS/active/' or '💬 SESSIONS/'. Use '' for root."
                    ),
                }
            },
            "required": ["path"],
        },
    },
]

MAX_VAULT_FILE_SIZE = 12000  # Truncate large files to avoid blowing context


async def fetch_vault_file(path: str) -> str:
    """Fetch any file from Trinity Brain vault on GitHub."""
    if not GITHUB_TOKEN:
        return "Error: GITHUB_TOKEN not configured — cannot access vault"
    encoded_path = urllib.parse.quote(path, safe="/")
    url = f"https://api.github.com/repos/cc404ssis/TRINITYBRAIN/contents/{encoded_path}"

    def _fetch():
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"token {GITHUB_TOKEN}")
        req.add_header("Accept", "application/vnd.github.v3+json")
        req.add_header("User-Agent", "CB404-Discord-Bot")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        content = base64.b64decode(data["content"]).decode("utf-8")
        if len(content) > MAX_VAULT_FILE_SIZE:
            return content[:MAX_VAULT_FILE_SIZE] + (
                f"\n\n[Truncated — file is {len(content)} chars, showing first {MAX_VAULT_FILE_SIZE}]"
            )
        return content

    try:
        return await asyncio.to_thread(_fetch)
    except Exception as e:
        return f"Error reading '{path}': {e}"


async def list_vault_directory(path: str) -> str:
    """List contents of a vault directory on GitHub."""
    if not GITHUB_TOKEN:
        return "Error: GITHUB_TOKEN not configured — cannot access vault"
    encoded_path = urllib.parse.quote(path, safe="/") if path else ""
    url = f"https://api.github.com/repos/cc404ssis/TRINITYBRAIN/contents/{encoded_path}"

    def _fetch():
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"token {GITHUB_TOKEN}")
        req.add_header("Accept", "application/vnd.github.v3+json")
        req.add_header("User-Agent", "CB404-Discord-Bot")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if isinstance(data, list):
            entries = []
            for item in sorted(data, key=lambda x: (x["type"] != "dir", x["name"])):
                icon = "\U0001f4c1" if item["type"] == "dir" else "\U0001f4c4"
                entries.append(f"{icon} {item['name']}")
            return "\n".join(entries)
        return "Path is a file, not a directory. Use read_vault_file instead."

    try:
        return await asyncio.to_thread(_fetch)
    except Exception as e:
        return f"Error listing '{path}': {e}"


async def execute_vault_tool(name: str, input_data: dict) -> str:
    """Execute a vault tool and return the result as a string."""
    if name == "read_vault_file":
        return await fetch_vault_file(input_data["path"])
    if name == "list_vault_directory":
        return await list_vault_directory(input_data["path"])
    return f"Unknown tool: {name}"


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


IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20 MB


async def download_image(attachment: discord.Attachment) -> dict | None:
    """Download a Discord image attachment and return a Claude image content block."""
    content_type = (attachment.content_type or "").split(";")[0]
    if content_type not in IMAGE_TYPES:
        return None
    if attachment.size > MAX_IMAGE_SIZE:
        return None
    try:
        data = await attachment.read()
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": content_type,
                "data": base64.b64encode(data).decode("utf-8"),
            },
        }
    except Exception:
        return None


def _merge_content(existing, new_content):
    """Merge two content values, handling both string and list-of-blocks formats."""
    if isinstance(existing, str) and isinstance(new_content, str):
        return existing + "\n" + new_content
    # At least one side has image blocks — normalize both to lists
    if isinstance(existing, str):
        existing = [{"type": "text", "text": existing}]
    if isinstance(new_content, str):
        new_content = [{"type": "text", "text": new_content}]
    return existing + new_content


async def build_conversation(message: discord.Message, history: list[discord.Message]) -> list[dict]:
    """
    Build a Claude conversation from Discord channel history.
    History is oldest-first (already reversed from Discord's newest-first fetch).
    The triggering message is appended at the end as the final user turn.
    Supports image attachments via Claude's vision API.
    """
    messages = []

    for msg in history:
        if msg.id == message.id:
            continue  # Skip the trigger message — we'll add it at the end

        # Note image attachments in history but don't download them
        # (downloading base64 images from 20 messages blows up request size → 413)
        has_images = any(
            (att.content_type or "").split(";")[0] in IMAGE_TYPES for att in msg.attachments
        )

        text = msg.content.strip()
        if not text and not has_images:
            continue

        # Label bot messages by name so Claude knows who said what
        if msg.author.bot:
            text = f"[{msg.author.display_name}] {text}" if text else f"[{msg.author.display_name}] (shared an image)"
        elif not text:
            text = "(shared an image)"

        # Alternate user/assistant roles: human messages → user, bots → assistant
        # This keeps Claude's conversation format valid
        role = "assistant" if msg.author.bot else "user"

        # History messages are text-only (images noted but not downloaded)
        content = text

        # Merge consecutive same-role messages
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] = _merge_content(messages[-1]["content"], content)
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

    # Download images from the triggering message
    trigger_images = []
    for att in message.attachments:
        block = await download_image(att)
        if block:
            trigger_images.append(block)

    if not clean_content and not trigger_images:
        clean_content = "(pinged with no additional text)"
    elif not clean_content:
        clean_content = "(shared an image)"

    trigger_content = trigger_images + [{"type": "text", "text": clean_content}] if trigger_images else clean_content

    if messages and messages[-1]["role"] == "user":
        messages[-1]["content"] = _merge_content(messages[-1]["content"], trigger_content)
    else:
        messages.append({"role": "user", "content": trigger_content})

    # Claude API requires messages to start with 'user'
    if messages and messages[0]["role"] == "assistant":
        messages = messages[1:]

    return messages if messages else [{"role": "user", "content": trigger_content}]


async def get_claude_response(messages: list[dict]) -> str:
    """Call Claude with vault tool use. Uses Opus 4.6 with Sonnet 4.6 fallback on overload."""
    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    models = ["claude-opus-4-6", "claude-sonnet-4-6"]
    system = (
        f"{SYSTEM_PROMPT}\n\n{PROJECT_CONTEXT}"
        + (f"\n\n## Live Priorities\n{_dynamic_context}" if _dynamic_context else "")
    )
    tools = VAULT_TOOLS if GITHUB_TOKEN else []

    for model in models:
        delay = 2
        max_retries = 3
        for attempt in range(max_retries):
            try:
                loop_messages = list(messages)

                for _ in range(4):  # Max 4 tool rounds
                    kwargs = dict(
                        model=model,
                        max_tokens=4096,
                        thinking={"type": "adaptive"},
                        system=system,
                        messages=loop_messages,
                    )
                    if tools:
                        kwargs["tools"] = tools

                    response = await client.messages.create(**kwargs)

                    if response.stop_reason != "tool_use":
                        # Extract text blocks from final response
                        return "".join(
                            block.text for block in response.content if hasattr(block, "text")
                        )

                    # Execute any tool calls
                    tool_results = []
                    for block in response.content:
                        if block.type == "tool_use":
                            result = await execute_vault_tool(block.name, block.input)
                            tool_results.append(
                                {"type": "tool_result", "tool_use_id": block.id, "content": result}
                            )

                    # Feed tool results back for the next round
                    loop_messages.append({"role": "assistant", "content": response.content})
                    loop_messages.append({"role": "user", "content": tool_results})

                # Exhausted tool rounds — return whatever text we have
                return "".join(
                    block.text for block in response.content if hasattr(block, "text")
                )

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

            # Build Claude conversation (async to support image downloads)
            messages = await build_conversation(message, history)

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
