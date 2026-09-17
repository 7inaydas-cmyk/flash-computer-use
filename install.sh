#!/usr/bin/env bash
# Deploy flash-computer-use artifacts to their live locations.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"

install -m 0755 "$here/bin/lcu"              ~/.local/bin/lcu
install -m 0755 "$here/bin/flash-relay"      ~/.local/bin/flash-relay
mkdir -p ~/.openwork/lcu-mcp
install -m 0644 "$here/mcp/lcu-mcp-server.py" ~/.openwork/lcu-mcp/server.py
mkdir -p ~/.zcode/agents
install -m 0644 "$here/agents/flash-worker.md" ~/.zcode/agents/flash-worker.md
mkdir -p ~/.agents/skills/flash-computer-use
install -m 0644 "$here/skills/flash-computer-use/SKILL.md" ~/.agents/skills/flash-computer-use/SKILL.md

echo "Deployed lcu, flash-relay, lcu-mcp, the flash-worker profile, and the skill."
echo "Manual steps left:"
echo "  1. Merge zcode-cli-config.example.json into ~/.zcode/cli/config.json"
echo "     (mcp.servers.lcu; provider record; model string; apiKey from your own store)."
echo "  2. Restart ZCode so the profile, skill, and MCP server register."
echo "  3. Validate: lcu windows && zcode skills list"
