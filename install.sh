#!/usr/bin/env bash
# aos control: switch on the Linux side for the current user. Safe to re-run.
#   bash install.sh              check prerequisites, then install the runner timer and the agenda hook
#   bash install.sh --discord    also the Discord phone agent + aos-watch (after the Discord bot is set up and paired)
#   bash install.sh --rc         also Claude Remote Control (start sessions on this PC from the Claude phone app)
#   bash install.sh --vnc        also wayvnc on the Tailscale IP (needs wayvnc + Tailscale)
#   bash install.sh --agent-desk also the headless agent desktop service (Hyprland setups; not started)
#   bash install.sh --plan       print every step and change nothing (combine with the flags above)
#   bash install.sh doctor       read-only health check (exit 0 only when every required check passes)
# systemd/*.service and *.timer are templates: this script fills in this checkout's path, your work folder and the
# bun/claude/tmux it finds on PATH, and writes the result to ~/.config/systemd/user/.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
UNITS="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SETTINGS="$HOME/.claude/settings.json"
ENV_FILE="$HERE/.env.local"
CORE_UNITS=(aos-tick.service aos-tick.timer aos-discord.service aos-discord-fresh.service aos-discord-fresh.timer
  aos-watch.service claude-rc.service aos-vnc.service)

PLAN=0 DISCORD=0 VNC=0 RC=0 AGENT_DESK=0 DOCTOR=0
for arg in "$@"; do
  case "$arg" in
    --plan) PLAN=1 ;;
    --discord) DISCORD=1 ;;
    --vnc) VNC=1 ;;
    --rc) RC=1 ;;
    --agent-desk) AGENT_DESK=1 ;;
    doctor|--doctor) DOCTOR=1 ;;
    -h|--help) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $arg (use --plan, --discord, --rc, --vnc, --agent-desk or doctor)" >&2; exit 2 ;;
  esac
done

# A setting from the environment, else from .env.local (never printed).
conf() {
  local v="${!1:-}"
  [ -n "$v" ] || v=$(sed -n "s/^$1=//p" "$ENV_FILE" 2>/dev/null | tail -1 | sed "s/^[\"']//; s/[\"']\$//")
  printf '%s' "$v"
}
on() { [[ $(conf "$1") =~ ^(1|true|yes|on)$ ]]; }

WORKDIR="$(conf AOS_WORKDIR)"; WORKDIR="${WORKDIR:-$HOME}"; WORKDIR="${WORKDIR/#\~/$HOME}"
RC_NAME="$(conf AOS_RC_NAME)"; RC_NAME="${RC_NAME:-linux}"
BUN="$(command -v bun || true)"
CLAUDE="$(command -v claude || true)"
NODE="$(command -v node || true)"
TMUX_BIN="$(command -v tmux || true)"
UV="$(command -v uv || true)"
HOOK_CMD="cd $(printf '%q' "$HERE") && $(printf '%q' "${BUN:-bun}") hooks/agenda.ts"

# PATH for the services: where bun, claude, node, uv and tmux live, then ~/.local/bin and the system dirs.
svc_path() {
  local p="" d
  for d in ${BUN:+"$(dirname "$BUN")"} ${CLAUDE:+"$(dirname "$CLAUDE")"} ${NODE:+"$(dirname "$NODE")"} \
           ${UV:+"$(dirname "$UV")"} ${TMUX_BIN:+"$(dirname "$TMUX_BIN")"} "$HOME/.local/bin" /usr/local/bin /usr/bin /bin; do
    case "$d" in /usr/local/bin|/usr/bin|/bin) continue ;; esac # system dirs go last, in their usual order
    case ":$p:" in *":$d:"*) ;; *) p="${p:+$p:}$d" ;; esac
  done
  p="${p:+$p:}/usr/local/bin:/usr/bin:/bin"
  printf '%s' "$p"
}
SVC_PATH="$(svc_path)"

# Fills in one template. Paths with | or newlines would break the substitution, so they are refused up front.
render() {
  sed -e "s|@REPO@|$HERE|g" -e "s|@WORKDIR@|$WORKDIR|g" -e "s|@PATH@|$SVC_PATH|g" \
      -e "s|@BUN@|${BUN:-bun}|g" -e "s|@CLAUDE@|${CLAUDE:-claude}|g" -e "s|@TMUX@|${TMUX_BIN:-tmux}|g" \
      -e "s|@UV@|${UV:-uv}|g" -e "s|@RC_NAME@|$RC_NAME|g" \
      -e "s|@DISPLAY@|${DISPLAY:-:0}|g" -e "s|@WAYLAND_DISPLAY@|${WAYLAND_DISPLAY:-wayland-1}|g" \
      "$HERE/systemd/$1"
}
for v in "$HERE" "$WORKDIR" "$SVC_PATH" "$RC_NAME"; do
  case "$v" in *'|'*|*$'\n'*) echo "path or name contains | or a newline, which install.sh cannot template: $v" >&2; exit 2 ;; esac
done

ok()   { printf '  OK       %s\n' "$1"; }
miss() { printf '  MISSING  %s\n' "$1"; fail=1; }
warn() { printf '  OPTIONAL %s\n' "$1"; }

claude_logged_in() {
  [ -n "$CLAUDE" ] || return 1
  "$CLAUDE" auth status --json 2>/dev/null | python3 -I -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("loggedIn") else 1)' 2>/dev/null
}

check_tools() {
  echo "prerequisites"
  for t in bun node claude tmux python3 curl systemctl; do
    command -v "$t" >/dev/null && ok "$t" || miss "$t (required)"
  done
  if claude_logged_in; then ok "Claude Code logged in"; else miss "Claude Code not logged in (run: claude auth login)"; fi
  if systemctl --user show-environment >/dev/null 2>&1; then ok "systemd user session"; else miss "systemd user session (systemctl --user does not answer)"; fi
  echo "desk MCP (optional, Hyprland only)"
  for t in hyprctl kitty grim wl-copy uv systemd-inhibit; do
    command -v "$t" >/dev/null && ok "$t" || warn "$t not installed (only the desk MCP needs it)"
  done
  echo "remote desktop (optional)"
  for t in wayvnc tailscale cage; do command -v "$t" >/dev/null && ok "$t" || warn "$t not installed"; done
}

# Set and not a placeholder from .env.example (like https://<your-app>.vercel.app/api/mcp).
has_key() { local v; v="$(conf "$1")"; [ -n "$v" ] && [[ $v != *"<"* ]]; }

# ---------- doctor: read only ----------
if [ "$DOCTOR" = 1 ]; then
  fail=0
  echo "aos doctor: $HERE"
  check_tools
  echo "config ($ENV_FILE)"
  if [ -f "$ENV_FILE" ]; then
    for k in SUPABASE_URL SUPABASE_SERVICE_ROLE_KEY AOS_MCP_URL AOS_MCP_TOKEN; do
      has_key "$k" && ok ".env.local has $k" || miss ".env.local lacks $k"
    done
    for k in DISCORD_WEBHOOK_URL AOS_OWNER_NAME AOS_OWNERS AOS_WORKDIR; do
      has_key "$k" && ok ".env.local has $k" || warn ".env.local has no $k (default used)"
    done
  else miss ".env.local (run install.sh once to create it from .env.example)"; fi
  [ -d "$WORKDIR" ] && ok "work folder $WORKDIR" || miss "work folder $WORKDIR (AOS_WORKDIR) does not exist"
  [ -f "$HERE/config/ventures.json" ] && ok "config/ventures.json" || warn "config/ventures.json not found (default ventures used)"
  [ -d "$HERE/node_modules" ] && ok "node_modules (bun install / npm ci done)" || miss "node_modules (run: npm ci)"
  echo "systemd user units ($UNITS)"
  for f in "${CORE_UNITS[@]}"; do
    if [ -f "$UNITS/$f" ] && [ ! -L "$UNITS/$f" ] && [ "$(render "$f")" = "$(cat "$UNITS/$f")" ]; then ok "$f installed"
    elif [ -L "$UNITS/$f" ]; then miss "$f is an old symlink (re-run install.sh to write the rendered unit)"
    elif [ -f "$UNITS/$f" ]; then miss "$f out of date (re-run install.sh)"
    else miss "$f not installed (run install.sh)"; fi
  done
  [ "$(systemctl --user is-active aos-tick.timer 2>/dev/null)" = active ] && ok "aos-tick.timer active" || miss "aos-tick.timer not active"
  for u in claude-rc.service aos-discord.service aos-watch.service aos-discord-fresh.timer aos-vnc.service; do
    s="$(systemctl --user is-active "$u" 2>/dev/null || true)"
    [ "$s" = active ] && ok "$u active" || warn "$u ${s:-inactive} (needs --rc / --discord / --vnc)"
  done
  echo "Discord (optional)"
  [ -f "$HOME/.claude/channels/discord/.env" ] && ok "Discord plugin token saved" || warn "no ~/.claude/channels/discord/.env (README: Discord bot)"
  [ -f "$HOME/.claude/channels/discord/access.json" ] && ok "Discord plugin paired" || warn "Discord plugin not paired yet"
  echo "Claude Code"
  if python3 -I - "$SETTINGS" "$HOOK_CMD" <<'PY'
import json, sys
try:
    hooks = json.load(open(sys.argv[1])).get("hooks", {}).get("SessionStart", [])
except (OSError, ValueError):
    sys.exit(1)
sys.exit(0 if any(h.get("hooks", [{}])[0].get("command") == sys.argv[2] for h in hooks) else 1)
PY
  then ok "SessionStart agenda hook"; else miss "SessionStart agenda hook (run install.sh)"; fi
  mcp_has() {
    python3 -I - "$HOME/.claude.json" "$1" <<'PY'
import json, sys
try:
    servers = json.load(open(sys.argv[1])).get("mcpServers", {})
except (OSError, ValueError):
    sys.exit(1)
sys.exit(0 if sys.argv[2] in servers else 1)
PY
  }
  mcp_has aos && ok "MCP server aos (user scope)" || miss "MCP server aos at user scope (README: claude mcp add)"
  mcp_has desk && ok "MCP server desk (user scope)" || warn "MCP server desk not added (optional, Hyprland only)"
  if on AOS_EXTRA_UNLOCK || on AOS_EXTRA_BOOT; then
    echo "extras (extras/README.md)"
    [ -S /run/aos-unlock.sock ] && ok "aos-unlock service" || warn "aos-unlock not installed (sudo bash extras/boot/unlock/install.sh)"
    grep -qs '\[initial_session\]' /etc/greetd/config.toml && ok "boot auto-login" || warn "boot auto-login off (sudo bash extras/boot/apply.sh)"
  fi
  [ "$fail" = 0 ] && echo "all required checks pass" || echo "some required checks failed"
  exit "$fail"
fi

# ---------- install (or --plan) ----------
do_() { if [ "$PLAN" = 1 ]; then printf '   would run: %s\n' "$*"; else "$@"; fi; }
[ "$PLAN" = 1 ] && echo "PLAN ONLY: nothing below is changed"
echo "aos install: repo $HERE, work folder $WORKDIR"

echo "0/4 prerequisites"
fail=0
check_tools
if [ "$fail" = 1 ]; then
  if [ "$PLAN" = 1 ]; then echo "   (install would stop here until the MISSING items above are fixed)"
  else echo "Fix the MISSING items above, then run install.sh again."; exit 1; fi
fi

echo "1/4 config"
if [ ! -f "$ENV_FILE" ]; then
  if [ "$PLAN" = 1 ]; then
    echo "   would copy .env.example to .env.local (mode 600) and stop so you can fill it in"
  else
    install -m 600 "$HERE/.env.example" "$ENV_FILE"
    cat <<EOF
Created $ENV_FILE from .env.example. Next steps:
  1. Fill in SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, AOS_MCP_URL and AOS_MCP_TOKEN (README: Quick start).
  2. Optional: AOS_OWNER_NAME, AOS_OWNERS, AOS_WORKDIR, DISCORD_WEBHOOK_URL.
  3. Run: bash $HERE/install.sh
EOF
    exit 1
  fi
else
  missing=()
  for k in SUPABASE_URL SUPABASE_SERVICE_ROLE_KEY AOS_MCP_URL AOS_MCP_TOKEN; do has_key "$k" || missing+=("$k"); done
  if [ "${#missing[@]}" -gt 0 ]; then
    if [ "$PLAN" = 1 ]; then echo "   .env.local lacks ${missing[*]}: install would stop here"
    else echo "Fill in ${missing[*]} in $ENV_FILE (README: Quick start), then run install.sh again."; exit 1; fi
  else
    echo "   .env.local has the required keys"
  fi
fi
[ -d "$WORKDIR" ] || { echo "AOS_WORKDIR $WORKDIR does not exist" >&2; [ "$PLAN" = 1 ] || exit 1; }

echo "2/4 systemd user units ($UNITS)"
units=("${CORE_UNITS[@]}")
[ "$AGENT_DESK" = 1 ] && units+=(aos-agent-desk.service)
do_ mkdir -p "$UNITS"
for f in "${units[@]}"; do
  if [ "$PLAN" = 1 ]; then
    echo "   would write $UNITS/$f (from systemd/$f):"
    render "$f" | grep -E '^(ExecStart|ExecStop|WorkingDirectory|Environment)=' | sed 's/^/      /' || true
  else
    rm -f "$UNITS/$f" # an older install linked the template itself; never write through that link
    render "$f" > "$UNITS/$f"
  fi
done
do_ systemctl --user daemon-reload
do_ systemctl --user enable --now aos-tick.timer
[ "$RC" = 1 ] && do_ systemctl --user enable --now claude-rc.service
if [ "$DISCORD" = 1 ]; then
  [ -f "$HOME/.claude/channels/discord/.env" ] || { echo "Discord plugin not set up yet (README: Discord bot)"; [ "$PLAN" = 1 ] || exit 1; }
  do_ systemctl --user enable --now aos-discord.service aos-watch.service aos-discord-fresh.timer
fi
if [ "$VNC" = 1 ]; then
  command -v wayvnc >/dev/null || { echo "wayvnc missing: sudo apt install -y wayvnc"; [ "$PLAN" = 1 ] || exit 1; }
  do_ systemctl --user enable --now aos-vnc.service
fi
[ "$AGENT_DESK" = 1 ] && do_ systemctl --user enable aos-agent-desk.service

echo "3/4 SessionStart hook (agenda in every Claude session)"
if [ "$PLAN" = 1 ]; then
  echo "   would back up $SETTINGS to settings.json.bak-aos and add the hook if it is missing:"
  echo "   $HOOK_CMD"
else
python3 -I - "$SETTINGS" "$HOOK_CMD" <<'PY'
import json, os, shutil, sys
p, cmd = sys.argv[1], sys.argv[2]
d = {}
if os.path.exists(p):
    shutil.copy(p, p + '.bak-aos')
    d = json.load(open(p))
else:
    os.makedirs(os.path.dirname(p), exist_ok=True)
hooks = d.setdefault('hooks', {}).setdefault('SessionStart', [])
if not any(h.get('hooks', [{}])[0].get('command') == cmd for h in hooks):
    hooks.append({'matcher': 'startup', 'hooks': [{'type': 'command', 'command': cmd, 'timeout': 10}]})
json.dump(d, open(p, 'w'), indent=2)
print('   hook present' + (' (backup: settings.json.bak-aos)' if os.path.exists(p + '.bak-aos') else ''))
PY
fi

echo "4/4 status"
if [ "$PLAN" = 1 ]; then
  echo "   would show the tick timer and any optional services that were switched on"
  exit 0
fi
systemctl --user list-timers aos-tick.timer --no-pager | head -2
[ "$RC" = 1 ] && { systemctl --user --no-pager --lines=5 status claude-rc.service | sed -n '1,8p' || true; }
if systemctl --user is-active aos-vnc.service >/dev/null 2>&1; then echo "   vnc: $(tailscale ip -4 | head -1):5900 (Tailscale only)"; fi
echo "Done. Logs: journalctl --user -u aos-tick -u claude-rc -u aos-discord -u aos-vnc -f"
echo "Health check any time: bash $HERE/install.sh doctor"
