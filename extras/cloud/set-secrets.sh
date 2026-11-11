#!/usr/bin/env bash
# Put aos-cloud's secrets on the VM. Run it yourself in a terminal (prompts are hidden, nothing is echoed):
#   bash extras/cloud/set-secrets.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# Settings come from .env.local (gitignored), or the environment.
conf() { sed -n "s/^$1=//p" "$(cd "$(dirname "$0")/../.." && pwd)/.env.local" 2>/dev/null | tail -1 | sed "s/^[\"']//; s/[\"']\$//"; }
VM="${AOS_VM:-$(conf AOS_VM)}"; : "${VM:?set AOS_VM=ubuntu@<VM Tailscale IP> in .env.local}"
read -rsp "aos-cloud Discord bot token: " DISCORD_TOKEN; echo
read -rp  "MeshCentral login token USERNAME (starts with ~t:): " MESH_USER
read -rsp "MeshCentral login token PASSWORD: " MESH_PASS; echo
read -rsp "Gemini API key (Enter to skip): " GEMINI_API_KEY; echo
AOS_MCP_TOKEN=$(conf AOS_MCP_TOKEN)
MESH_NODE_ID="${MESH_NODE_ID:-$(conf MESH_NODE_ID)}"; : "${MESH_NODE_ID:?set MESH_NODE_ID (MeshCentral node id of the PC, node//...) in .env.local}"
OWNER_NAME="${AOS_OWNER_NAME:-$(conf AOS_OWNER_NAME)}"
OWNER_ID=$(python3 -c "import json;print(json.load(open('$HOME/.claude/channels/discord/access.json'))['allowFrom'][0])")
{
  printf 'DISCORD_TOKEN=%s\n' "$DISCORD_TOKEN"
  printf 'MESH_USER=%s\nMESH_PASS=%s\n' "$MESH_USER" "$MESH_PASS"
  printf 'MESH_NODE_ID=%s\n' "$MESH_NODE_ID"
  printf 'PC_USER=%s\nPC_UID=%s\n' "$(id -un)" "$(id -u)"
  [[ -n "$OWNER_NAME" ]] && printf 'OWNER_NAME=%s\n' "$OWNER_NAME"
  printf 'AOS_MCP_TOKEN=%s\nOWNER_ID=%s\n' "$AOS_MCP_TOKEN" "$OWNER_ID"
  [[ -n "$GEMINI_API_KEY" ]] && printf 'GEMINI_API_KEY=%s\n' "$GEMINI_API_KEY"
} | ssh "$VM" 'sudo install -d -m 750 -o root -g aoscloud /etc/aos-cloud && sudo tee /etc/aos-cloud/env >/dev/null && sudo chown root:aoscloud /etc/aos-cloud/env && sudo chmod 640 /etc/aos-cloud/env && sudo systemctl enable --now aos-cloud >/dev/null 2>&1 && sudo systemctl restart aos-cloud && sleep 8 && sudo journalctl -u aos-cloud -n 4 --no-pager -o cat'
unset DISCORD_TOKEN MESH_PASS GEMINI_API_KEY AOS_MCP_TOKEN
