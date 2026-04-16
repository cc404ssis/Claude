"""
Claude Discord Bot — Studio404
Technical brain / architect persona for Studio404 server.

Core rules:
- Only responds when @mentioned by a HUMAN (never triggered by other bots)
- Reads recent channel history for context (sees Dr Mana + Kimi replies)
- Never @mentions other bots in replies (prevents loops)
- Uses Claude Opus 4.6 with adaptive thinking + vault + Discord tool use
"""

import io
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

try:
    from pptx import Presentation as PptxPresentation
    PPTX_AVAILABLE = True
except ImportError:
    PPTX_AVAILABLE = False

load_dotenv()

DISCORD_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GITHUB_TOKEN = os.environ.get("TRINITYBRAIN_GITHUB_TOKEN", "")
HISTORY_LIMIT = int(os.environ.get("HISTORY_LIMIT", "20"))
HISTORY_IMAGE_LIMIT = int(os.environ.get("HISTORY_IMAGE_LIMIT", "5"))
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
You have two sets of tools available:

**Trinity Brain vault tools:**
- **read_vault_file** — Read any file by path (e.g. '🧠 SYSTEM/PRIORITIES.md')
- **list_vault_directory** — Browse directories to discover files (e.g. '📁 PROJECTS/active/')

**Discord server tools:**
- **list_channels** — List all channels in the Studio404 server
- **read_channel** — Read recent messages from any channel by name or ID
- **list_members** — List server members with their roles
- **pin_message** — Pin a message (use `last_bot` to pin your own last message, or pass a message ID from read_channel)
- **create_thread** — Create a public thread in the current channel or any specified channel
- **create_category** — Create a new category in the server
- **create_channel** — Create a new text channel, optionally inside a category
- **send_to_channel** — Send a message to a different channel
- **manage_role** — Add or remove a role from a member

When asked about a project, channel, or member you don't have context on — use your tools to look it up. The vault is the shared source of truth. Discord tools let you act on the server directly."""


# ── Project Context (update this freely) ──────────────────────────────────────
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


# ── Discord Tools ──────────────────────────────────────────────────────────────

DISCORD_TOOLS = [
    {
        "name": "list_channels",
        "description": "List all text channels and categories in the Studio404 Discord server.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "read_channel",
        "description": (
            "Read recent messages from any channel in the server, including message IDs. "
            "Use to check what's being discussed in another channel, or to find a message ID before pinning."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "channel": {
                    "type": "string",
                    "description": "Channel name (e.g. 'general') or channel ID.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of messages to fetch (default 15, max 50).",
                },
            },
            "required": ["channel"],
        },
    },
    {
        "name": "list_members",
        "description": "List all members in the Studio404 server with their display names and roles.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "pin_message",
        "description": (
            "Pin a message in the current channel. "
            "Pass message_id='last_bot' to pin the most recent CB404 message in the channel. "
            "Otherwise pass the specific message ID (use read_channel to find IDs)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "Message ID to pin, or 'last_bot' to pin the most recent CB404 message.",
                },
            },
            "required": ["message_id"],
        },
    },
    {
        "name": "create_thread",
        "description": "Create a public thread. Creates in the current channel by default, or in a specified channel.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name for the new thread (max 100 characters).",
                },
                "channel": {
                    "type": "string",
                    "description": "Optional: channel name or ID to create the thread in. Defaults to current channel.",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "create_category",
        "description": "Create a new category in the Discord server.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the category to create.",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "create_channel",
        "description": "Create a new text channel in the server, optionally inside a category.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the channel to create (lowercase, no spaces — use hyphens).",
                },
                "category": {
                    "type": "string",
                    "description": "Optional: category name or ID to place the channel in.",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "send_to_channel",
        "description": "Send a message to a different channel in the server.",
        "input_schema": {
            "type": "object",
            "properties": {
                "channel": {
                    "type": "string",
                    "description": "Target channel name (e.g. 'announcements') or channel ID.",
                },
                "content": {
                    "type": "string",
                    "description": "The message text to send.",
                },
            },
            "required": ["channel", "content"],
        },
    },
    {
        "name": "manage_role",
        "description": "Add or remove a role from a server member.",
        "input_schema": {
            "type": "object",
            "properties": {
                "member": {
                    "type": "string",
                    "description": "Member display name or user ID.",
                },
                "role": {
                    "type": "string",
                    "description": "Role name or role ID.",
                },
                "action": {
                    "type": "string",
                    "enum": ["add", "remove"],
                    "description": "Whether to add or remove the role.",
                },
            },
            "required": ["member", "role", "action"],
        },
    },
]

DISCORD_TOOL_NAMES = {t["name"] for t in DISCORD_TOOLS}
VAULT_TOOL_NAMES = {t["name"] for t in VAULT_TOOLS}


def _find_channel(guild: discord.Guild, name_or_id: str) -> discord.TextChannel | None:
    """Find a text channel by name or ID."""
    try:
        cid = int(name_or_id)
        return guild.get_channel(cid)
    except ValueError:
        clean = name_or_id.lstrip("#")
        return discord.utils.find(lambda c: c.name == clean, guild.text_channels)


def _find_member(guild: discord.Guild, name_or_id: str) -> discord.Member | None:
    """Find a member by display name, username, or ID."""
    try:
        mid = int(name_or_id)
        return guild.get_member(mid)
    except ValueError:
        lower = name_or_id.lower()
        return discord.utils.find(
            lambda m: m.display_name.lower() == lower or m.name.lower() == lower,
            guild.members,
        )


def _find_role(guild: discord.Guild, name_or_id: str) -> discord.Role | None:
    """Find a role by name or ID."""
    try:
        rid = int(name_or_id)
        return guild.get_role(rid)
    except ValueError:
        lower = name_or_id.lower()
        return discord.utils.find(lambda r: r.name.lower() == lower, guild.roles)


async def execute_discord_tool(
    name: str,
    input_data: dict,
    bot_ref: commands.Bot,
    ctx_message: discord.Message,
) -> str:
    """Execute a Discord server tool and return a result string."""
    guild = ctx_message.guild
    if not guild:
        return "Error: Discord tools only work in a server channel, not DMs."

    # ── list_channels ──
    if name == "list_channels":
        lines = []
        seen_categories: set[str] = set()
        for ch in sorted(guild.text_channels, key=lambda c: (c.category.position if c.category else -1, c.position)):
            cat_name = ch.category.name if ch.category else "No Category"
            if cat_name not in seen_categories:
                lines.append(f"\n**{cat_name}**")
                seen_categories.add(cat_name)
            lines.append(f"  #{ch.name} (ID: {ch.id})")
        return "\n".join(lines).strip() or "No channels found."

    # ── read_channel ──
    if name == "read_channel":
        channel = _find_channel(guild, input_data["channel"])
        if not channel:
            return f"Channel '{input_data['channel']}' not found."
        limit = min(int(input_data.get("limit") or 15), 50)
        msgs: list[discord.Message] = []
        try:
            async for msg in channel.history(limit=limit):
                msgs.append(msg)
        except discord.Forbidden:
            return f"Error: Bot doesn't have permission to read #{channel.name}."
        msgs.reverse()
        lines = [f"#{channel.name} — last {len(msgs)} messages:"]
        for msg in msgs:
            ts = msg.created_at.strftime("%Y-%m-%d %H:%M")
            text = (msg.content[:200] + "…") if len(msg.content) > 200 else (msg.content or "(no text)")
            attachment_note = f" [+{len(msg.attachments)} file(s)]" if msg.attachments else ""
            lines.append(f"[{ts}] [ID:{msg.id}] {msg.author.display_name}: {text}{attachment_note}")
        return "\n".join(lines)

    # ── list_members ──
    if name == "list_members":
        lines = [f"Members in {guild.name} ({guild.member_count} total):"]
        for member in sorted(guild.members, key=lambda m: m.display_name.lower()):
            bot_flag = " [BOT]" if member.bot else ""
            roles = [r.name for r in member.roles if r.name != "@everyone"]
            role_str = ", ".join(roles) if roles else "no roles"
            lines.append(f"  {member.display_name} ({member.name}){bot_flag} — {role_str}")
        return "\n".join(lines)

    # ── pin_message ──
    if name == "pin_message":
        msg_id_raw = input_data["message_id"]
        try:
            if msg_id_raw == "last_bot":
                # Find the most recent CB404 message in the current channel
                target_msg = None
                async for m in ctx_message.channel.history(limit=50):
                    if m.author == bot_ref.user:
                        target_msg = m
                        break
                if not target_msg:
                    return "No recent CB404 messages found in this channel to pin."
            else:
                target_msg = await ctx_message.channel.fetch_message(int(msg_id_raw))
            await target_msg.pin()
            preview = (target_msg.content[:80] + "…") if len(target_msg.content) > 80 else target_msg.content
            return f"Pinned message from {target_msg.author.display_name}: {preview}"
        except discord.NotFound:
            return f"Message ID {msg_id_raw} not found in this channel."
        except discord.Forbidden:
            return "Error: Bot needs Manage Messages permission to pin."
        except ValueError:
            return "Error: Invalid message ID — must be a number or 'last_bot'."

    # ── create_thread ──
    if name == "create_thread":
        thread_name = input_data["name"][:100]
        # Optionally create in a different channel
        target_channel = ctx_message.channel
        if input_data.get("channel"):
            found = _find_channel(guild, input_data["channel"])
            if not found:
                return f"Channel '{input_data['channel']}' not found."
            target_channel = found
        try:
            thread = await target_channel.create_thread(name=thread_name, type=discord.ChannelType.public_thread)
            return f"Created thread '{thread.name}' (ID: {thread.id}) in #{target_channel.name}."
        except discord.Forbidden:
            return "Error: Bot needs Create Public Threads permission."
        except Exception as e:
            return f"Error creating thread: {e}"

    # ── create_category ──
    if name == "create_category":
        try:
            category = await guild.create_category(input_data["name"])
            return f"Created category '{category.name}' (ID: {category.id})."
        except discord.Forbidden:
            return "Error: Bot needs Manage Channels permission to create categories."
        except Exception as e:
            return f"Error creating category: {e}"

    # ── create_channel ──
    if name == "create_channel":
        category = None
        if input_data.get("category"):
            cat_name_or_id = input_data["category"]
            try:
                cat_id = int(cat_name_or_id)
                category = guild.get_channel(cat_id)
            except ValueError:
                lower = cat_name_or_id.lower()
                category = discord.utils.find(
                    lambda c: isinstance(c, discord.CategoryChannel) and c.name.lower() == lower,
                    guild.channels,
                )
            if not category:
                return f"Category '{input_data['category']}' not found. Create it first with create_category."
        try:
            channel = await guild.create_text_channel(input_data["name"], category=category)
            loc = f" in category '{category.name}'" if category else ""
            return f"Created channel #{channel.name} (ID: {channel.id}){loc}."
        except discord.Forbidden:
            return "Error: Bot needs Manage Channels permission to create channels."
        except Exception as e:
            return f"Error creating channel: {e}"

    # ── send_to_channel ──
    if name == "send_to_channel":
        channel = _find_channel(guild, input_data["channel"])
        if not channel:
            return f"Channel '{input_data['channel']}' not found."
        content = input_data["content"][:2000]
        try:
            await channel.send(content)
            return f"Sent to #{channel.name}."
        except discord.Forbidden:
            return f"Error: Bot doesn't have permission to send messages in #{channel.name}."

    # ── manage_role ──
    if name == "manage_role":
        member = _find_member(guild, input_data["member"])
        if not member:
            return f"Member '{input_data['member']}' not found."
        role = _find_role(guild, input_data["role"])
        if not role:
            return f"Role '{input_data['role']}' not found."
        action = input_data["action"]
        try:
            if action == "add":
                await member.add_roles(role)
                return f"Added role '{role.name}' to {member.display_name}."
            else:
                await member.remove_roles(role)
                return f"Removed role '{role.name}' from {member.display_name}."
        except discord.Forbidden:
            return "Error: Bot needs Manage Roles permission, or the role is above the bot's highest role."

    return f"Unknown Discord tool: {name}"


# ── Attachment Handling ────────────────────────────────────────────────────────

IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
PPTX_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
PDF_TYPE = "application/pdf"

TEXT_MIME_PREFIXES = ("text/",)
TEXT_MIME_TYPES = {
    "application/json",
    "application/xml",
    "application/x-yaml",
    "application/yaml",
    "application/toml",
    "application/javascript",
    "application/typescript",
}

CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs", ".c", ".cpp",
    ".h", ".hpp", ".cs", ".rb", ".php", ".swift", ".kt", ".scala", ".r",
    ".sh", ".bash", ".zsh", ".fish", ".ps1",
    ".md", ".txt", ".rst", ".csv", ".tsv",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".env", ".cfg", ".conf",
    ".html", ".htm", ".css", ".scss", ".sass", ".less",
    ".sql", ".graphql", ".proto", ".xml",
    ".dockerfile", ".makefile",
}

MAX_ATTACHMENT_SIZE = 20 * 1024 * 1024  # 20 MB
MAX_TEXT_FILE_SIZE = 20_000  # chars — truncate long text files


def _is_text_attachment(attachment: discord.Attachment) -> bool:
    """Return True if this attachment should be read as text."""
    ct = (attachment.content_type or "").split(";")[0].strip()
    if any(ct.startswith(p) for p in TEXT_MIME_PREFIXES):
        return True
    if ct in TEXT_MIME_TYPES:
        return True
    _, ext = os.path.splitext(attachment.filename.lower())
    return ext in CODE_EXTENSIONS


def extract_pptx_text(data: bytes) -> str:
    """Extract text from a PowerPoint file, formatted by slide."""
    if not PPTX_AVAILABLE:
        return "[PowerPoint file — install python-pptx to extract text]"
    try:
        prs = PptxPresentation(io.BytesIO(data))
        slides_text = []
        for i, slide in enumerate(prs.slides, 1):
            texts = []
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text.strip():
                    texts.append(shape.text.strip())
            if texts:
                slides_text.append(f"[Slide {i}]:\n" + "\n".join(texts))
        result = "\n\n".join(slides_text)
        if len(result) > MAX_TEXT_FILE_SIZE:
            result = result[:MAX_TEXT_FILE_SIZE] + f"\n\n[Truncated at {MAX_TEXT_FILE_SIZE} chars]"
        return result or "[Presentation has no readable text]"
    except Exception as e:
        return f"[Error extracting PowerPoint text: {e}]"


async def download_attachment(attachment: discord.Attachment) -> dict | None:
    """
    Download a Discord attachment and return a Claude content block, or None if unsupported.
    Handles: images, PDFs, text/code files, CSV, PPTX.
    """
    if attachment.size > MAX_ATTACHMENT_SIZE:
        return None

    ct = (attachment.content_type or "").split(";")[0].strip()
    filename = attachment.filename

    try:
        data = await attachment.read()
    except Exception:
        return None

    # ── Images ──
    if ct in IMAGE_TYPES:
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": ct,
                "data": base64.b64encode(data).decode("utf-8"),
            },
        }

    # ── PDFs (Claude native document support) ──
    if ct == PDF_TYPE or filename.lower().endswith(".pdf"):
        return {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": base64.b64encode(data).decode("utf-8"),
            },
        }

    # ── PowerPoint ──
    if ct == PPTX_TYPE or filename.lower().endswith(".pptx"):
        text = extract_pptx_text(data)
        return {"type": "text", "text": f"[File: {filename}]\n\n{text}"}

    # ── Text / code / CSV / markdown ──
    if _is_text_attachment(attachment):
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            return None
        if len(text) > MAX_TEXT_FILE_SIZE:
            text = text[:MAX_TEXT_FILE_SIZE] + f"\n\n[Truncated at {MAX_TEXT_FILE_SIZE} chars]"
        return {"type": "text", "text": f"[File: {filename}]\n\n{text}"}

    return None  # Unsupported type


def _merge_content(existing, new_content):
    """Merge two content values, handling both string and list-of-blocks formats."""
    if isinstance(existing, str) and isinstance(new_content, str):
        return existing + "\n" + new_content
    # At least one side has image/document blocks — normalize both to lists
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
    Supports image/document/text attachments for:
      - The trigger message (always downloaded)
      - The last HISTORY_IMAGE_LIMIT messages in history (downloaded for visual/doc context)
      - Older history messages (noted as text, not downloaded to keep request size small)
    """
    # Pre-download attachments for the last N history messages
    attachment_window = set()
    attachment_cache: dict[int, list[dict]] = {}
    if HISTORY_IMAGE_LIMIT > 0:
        recent = history[-HISTORY_IMAGE_LIMIT:]
        for msg in recent:
            if msg.attachments:
                attachment_window.add(msg.id)
                blocks = []
                for att in msg.attachments:
                    block = await download_attachment(att)
                    if block:
                        blocks.append(block)
                if blocks:
                    attachment_cache[msg.id] = blocks

    messages = []

    for msg in history:
        if msg.id == message.id:
            continue  # Skip the trigger message — added at the end

        text = msg.content.strip()

        # For messages inside the attachment window, use downloaded blocks
        if msg.id in attachment_window and msg.id in attachment_cache:
            blocks = attachment_cache[msg.id]
            if text:
                prefix = f"[{msg.author.display_name}] {text}" if msg.author.bot else text
                content = [{"type": "text", "text": prefix}] + blocks
            else:
                label = f"[{msg.author.display_name}] " if msg.author.bot else ""
                content = [{"type": "text", "text": f"{label}(shared files)"}] + blocks
        else:
            # For older messages, note attachments as text only
            has_attachments = bool(msg.attachments)
            if not text and not has_attachments:
                continue

            if msg.author.bot:
                if text:
                    text = f"[{msg.author.display_name}] {text}"
                if has_attachments and not text:
                    text = f"[{msg.author.display_name}] (shared files)"
                elif has_attachments:
                    text += " (+ files)"
            elif not text:
                text = "(shared files)"
            elif has_attachments:
                text += " (+ files)"

            content = text

        role = "assistant" if msg.author.bot else "user"

        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] = _merge_content(messages[-1]["content"], content)
        else:
            messages.append({"role": role, "content": content})

    # Append the triggering message as the final user turn
    clean_content = message.content
    for mention in message.mentions:
        clean_content = clean_content.replace(f"<@{mention.id}>", "").replace(
            f"<@!{mention.id}>", ""
        )
    clean_content = clean_content.strip()

    # Download all attachments from the triggering message
    trigger_blocks = []
    for att in message.attachments:
        block = await download_attachment(att)
        if block:
            trigger_blocks.append(block)

    if not clean_content and not trigger_blocks:
        clean_content = "(pinged with no additional text)"
    elif not clean_content:
        clean_content = "(shared files)"

    if trigger_blocks:
        trigger_content = [{"type": "text", "text": clean_content}] + trigger_blocks
    else:
        trigger_content = clean_content

    if messages and messages[-1]["role"] == "user":
        messages[-1]["content"] = _merge_content(messages[-1]["content"], trigger_content)
    else:
        messages.append({"role": "user", "content": trigger_content})

    # Claude API requires messages to start with 'user'
    if messages and messages[0]["role"] == "assistant":
        messages = messages[1:]

    return messages if messages else [{"role": "user", "content": trigger_content}]


async def classify_message_tier(text: str) -> str:
    """Classify a message as SIMPLE or COMPLEX using Haiku. Returns 'simple' or 'complex'."""
    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    try:
        response = await asyncio.wait_for(
            client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=32,
                system=(
                    "Classify the user's message as SIMPLE or COMPLEX. Respond with one word only.\n"
                    "SIMPLE: greetings, status checks, quick questions, acknowledgments, thank yous, "
                    "short follow-ups, yes/no answers, casual chat.\n"
                    "COMPLEX: architecture questions, code review, multi-step planning, tool use needed, "
                    "project analysis, debugging, system design, vault lookups, anything requiring deep reasoning, "
                    "anything involving Discord server actions (pinning, threading, reading channels, managing roles)."
                ),
                messages=[{"role": "user", "content": text}],
            ),
            timeout=5,
        )
        result = response.content[0].text.strip().lower()
        return "simple" if "simple" in result else "complex"
    except Exception:
        return "complex"  # Default to full pipeline on classification failure


async def get_simple_response(messages: list[dict]) -> str:
    """Handle simple messages with Haiku — no tools, no adaptive thinking."""
    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    system = (
        f"{SYSTEM_PROMPT}\n\n{PROJECT_CONTEXT}"
        + (f"\n\n## Live Priorities\n{_dynamic_context}" if _dynamic_context else "")
    )
    response = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=system,
        messages=messages,
    )
    return "".join(block.text for block in response.content if hasattr(block, "text"))


async def get_claude_response(
    messages: list[dict],
    bot_ref: commands.Bot | None = None,
    ctx_message: discord.Message | None = None,
) -> str:
    """
    Call Claude with vault + Discord tool use.
    Uses Opus 4.6 with Sonnet 4.6 fallback on overload.
    bot_ref and ctx_message are required for Discord tools to work.
    """
    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    models = ["claude-opus-4-6", "claude-sonnet-4-6"]
    system = (
        f"{SYSTEM_PROMPT}\n\n{PROJECT_CONTEXT}"
        + (f"\n\n## Live Priorities\n{_dynamic_context}" if _dynamic_context else "")
    )

    # Merge vault tools + Discord tools
    tools = []
    if GITHUB_TOKEN:
        tools.extend(VAULT_TOOLS)
    if bot_ref and ctx_message:
        tools.extend(DISCORD_TOOLS)

    for model in models:
        delay = 2
        max_retries = 3
        for attempt in range(max_retries):
            try:
                loop_messages = list(messages)

                for _ in range(8):  # Max 8 tool rounds (increased for multi-tool workflows)
                    kwargs: dict = dict(
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
                        return "".join(
                            block.text for block in response.content if hasattr(block, "text")
                        )

                    # Execute tool calls
                    tool_results = []
                    for block in response.content:
                        if block.type == "tool_use":
                            if block.name in VAULT_TOOL_NAMES:
                                result = await execute_vault_tool(block.name, block.input)
                            elif block.name in DISCORD_TOOL_NAMES and bot_ref and ctx_message:
                                result = await execute_discord_tool(
                                    block.name, block.input, bot_ref, ctx_message
                                )
                            else:
                                result = f"Tool '{block.name}' not available in this context."
                            tool_results.append(
                                {"type": "tool_result", "tool_use_id": block.id, "content": result}
                            )

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

        split_at = text.rfind("\n\n", 0, limit)
        if split_at == -1:
            split_at = text.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = text.rfind(". ", 0, limit)
            if split_at != -1:
                split_at += 1
        if split_at == -1:
            split_at = limit

        chunks.append(text[:split_at].strip())
        text = text[split_at:].strip()

    return [c for c in chunks if c]


# ── Bot setup ──────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True   # Privileged — must be enabled in Discord Developer Portal
intents.members = True           # Privileged — must be enabled in Discord Developer Portal

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    global _dynamic_context
    print(f"Claude bot online as {bot.user} (ID: {bot.user.id})")
    print(f"Connected to {len(bot.guilds)} server(s)")
    print(f"python-pptx available: {PPTX_AVAILABLE}")
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

            # Build Claude conversation (async to support attachment downloads)
            messages = await build_conversation(message, history)

            # Force complex tier if any attachments are present in the trigger message
            has_attachments = bool(message.attachments)
            tier = "complex" if has_attachments else await classify_message_tier(message.content)

            try:
                if tier == "simple":
                    response_text = await asyncio.wait_for(
                        get_simple_response(messages), timeout=30
                    )
                else:
                    response_text = await asyncio.wait_for(
                        get_claude_response(messages, bot_ref=bot, ctx_message=message),
                        timeout=120,
                    )
            except asyncio.TimeoutError:
                await message.reply("Timed out thinking about that — try again.", mention_author=False)
                return

            if not response_text.strip():
                await message.reply(
                    "(I processed that but had nothing to say — try rephrasing.)",
                    mention_author=False,
                )
                return

            chunks = split_response(response_text)
            for chunk in chunks:
                await message.reply(chunk, mention_author=False)

        except anthropic.RateLimitError:
            await message.reply(
                "Rate limited — give me a moment and ping me again.",
                mention_author=False,
            )
        except anthropic.APIError as e:
            await message.reply(f"API error: {str(e)}", mention_author=False)
        except Exception as e:
            print(f"Unexpected error: {e}")
            await message.reply("Something went wrong on my end. Try again.", mention_author=False)

    await bot.process_commands(message)


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
