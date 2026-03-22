# Claude + Obsidian = a literal cheat code

*How I use AI as my 2nd brain*

Connecting Claude to Obsidian via MCP lets you use AI to read, search, and write to your personal knowledge base — turning it into a true second brain.

## Quick Setup Steps

1. Install the **Obsidian Local REST API** plugin in Obsidian and enable it.
2. Copy your API key from the plugin settings.
3. Open Claude Desktop and go to **Edit Config**.
4. Paste the config below, replacing the placeholder values with your own.
5. Save the file and restart Claude Desktop.

## Claude Desktop Config

In the Edit Config section of Claude Desktop, use this JSON config. Replace `yourcomputer` with your machine username and `yourobsidiankey` with your Obsidian API key:

```json
{
  "mcpServers": {
    "mcp-obsidian": {
      "command": "/Users/yourcomputer/.local/bin/uvx",
      "args": [
        "mcp-obsidian"
      ],
      "env": {
        "OBSIDIAN_API_KEY": "yourobsidiankey"
      }
    }
  },
  "preferences": {
    "sidebarMode": "chat",
    "coworkScheduledTasksEnabled": false
  }
}
```

## Claude Code (CLI) Config

If using Claude Code instead of Claude Desktop, the MCP server is configured via `.claude/settings.json` in your project or home directory. See the `.claude/settings.json` file in this repo for the pre-configured template.

Replace `yourobsidiankey` with your actual Obsidian API key before use.
