#!/usr/bin/env bash
# Starts the phone agent: a Claude Code session that receives Discord DMs (Channels).
# Memory: a restart (crash, reboot, `agent restart`, an update) resumes the same conversation; once a day
# (aos-discord-fresh.timer, 04:00) it starts a new one, carried over by the aos agenda and the DM history.
# Every start first answers any of the owner's DMs that arrived while it was down (Discord does not redeliver them).
# Settings come from the repo's .env.local (or the environment): AOS_WORKDIR, AOS_OWNER_NAME, AOS_OWNERS,
# AOS_RUNNER_READ, AOS_AGENT_PROMPT_EXTRA, AOS_EXTRA_UNLOCK.
REPO="$(cd "$(dirname "$0")/.." && pwd)"
conf() { local v="${!1:-}"; [[ -n $v ]] || v=$(sed -n "s/^$1=//p" "$REPO/.env.local" 2>/dev/null | tail -1 | sed "s/^[\"']//; s/[\"']\$//"); printf '%s' "$v"; }

WORKDIR=$(conf AOS_WORKDIR); WORKDIR=${WORKDIR:-$HOME}; WORKDIR=${WORKDIR/#\~/$HOME}
cd "$WORKDIR" || exit 1
STATE=$HOME/.cache/aos
SID_FILE=$STATE/discord-session
FRESH=$STATE/discord-fresh
# Claude Code keeps a folder's transcripts under ~/.claude/projects/<path with every non-alphanumeric as ->.
TRANSCRIPTS=$HOME/.claude/projects/$(pwd -P | sed 's/[^A-Za-z0-9]/-/g')
mkdir -p "$STATE"

sid=$(cat "$SID_FILE" 2>/dev/null)
if [[ -f $FRESH || -z $sid || ! -f $TRANSCRIPTS/$sid.jsonl ]]; then
  rm -f "$FRESH"
  sid=$(cat /proc/sys/kernel/random/uuid)
  echo "$sid" > "$SID_FILE"
  session=(--session-id "$sid")
  start="New day, fresh session. "
else
  session=(--resume "$sid")
  start="You were restarted. "
fi

# The system prompt: systemd/discord-agent.md with the owner's details filled in, plus optional extras.
OWNER=$(conf AOS_OWNER_NAME); OWNER=${OWNER:-the user}
owners=$(conf AOS_OWNERS); SELF=me
IFS=',' read -ra list <<< "${owners,,}"
for o in "${list[@]}"; do o=${o// /}; [[ -n $o && $o != claude ]] && { SELF=$o; break; }; done
READ="CLAUDE.md"
IFS=',' read -ra reads <<< "$(conf AOS_RUNNER_READ)"
for r in "${reads[@]}"; do r=$(printf '%s' "$r" | xargs); [[ -n $r ]] && READ+=", $r"; done
prompt=$(cat "$REPO/systemd/discord-agent.md")
if [[ $(conf AOS_EXTRA_UNLOCK) =~ ^(1|true|yes|on)$ ]]; then prompt+=$'\n'$(cat "$REPO/extras/discord-agent-unlock.md"); fi
extra=$(conf AOS_AGENT_PROMPT_EXTRA); extra=${extra/#\~/$HOME}
if [[ -n $extra && -f $extra ]]; then prompt+=$'\n\n'$(cat "$extra"); fi
prompt=${prompt//\{\{OWNER\}\}/"$OWNER"}
prompt=${prompt//\{\{SELF\}\}/"$SELF"}
prompt=${prompt//\{\{WORKDIR\}\}/"$WORKDIR"}
prompt=${prompt//\{\{READ\}\}/"$READ"}
# `discord-agent.sh --print-prompt` shows the rendered prompt and exits (used by install.sh doctor).
if [[ ${1:-} == --print-prompt ]]; then printf '%s\n' "$prompt"; exit 0; fi

# The owner's DM channel id (looked up once with the bot token; the token never appears on a command line).
# desk/session_done_hook.py reads the same file.
DM_FILE=$STATE/discord-dm-channel
if [[ ! -s $DM_FILE ]]; then
  CH=$HOME/.claude/channels/discord
  owner=$(python3 -c "import json, sys; print(json.load(open(sys.argv[1]))['allowFrom'][0])" "$CH/access.json")
  curl -s -m 10 -X POST -H 'Content-Type: application/json' -d "{\"recipient_id\":\"$owner\"}" \
    -H @<(sed -n 's/^DISCORD_BOT_TOKEN=["'\'']\{0,1\}\([^"'\'']*\).*/Authorization: Bot \1/p' "$CH/.env") \
    https://discord.com/api/v10/users/@me/channels \
    | python3 -c 'import json, sys; print(json.load(sys.stdin).get("id", ""))' > "$DM_FILE" 2>/dev/null
fi
dm=$(cat "$DM_FILE" 2>/dev/null)
start+="Startup check (automatic, not a message from $OWNER): fetch the last 20 messages of $OWNER's Discord DM \
(fetch_messages, chat_id ${dm:-unknown: find it}). \
Answer every message of theirs from the last 3 hours that has no reply from you after it (it arrived while you were down); \
skip ones already answered by the Gemini fallback (🌐) or by an approval card. If there is nothing to answer, do nothing and say nothing."

# The plugin is disabled at user scope (it would log every Claude session in as the bot); enable it here only.
# Nobody watches this terminal, so commands the user settings only "ask" for are denied here: the session gets an
# error it can report on Discord instead of freezing at a prompt (aos-watch relays any prompt that still appears).
# Coordinator mode (if on in the user settings) is off here: dropped from the env and overridden in flag settings,
# which outrank user settings. ~/.claude/settings.json is left alone.
unset CLAUDE_CODE_COORDINATOR_MODE
exec claude "${session[@]}" --name aos-discord \
  --channels plugin:discord@claude-plugins-official --permission-mode auto --chrome \
  --settings '{"enabledPlugins":{"discord@claude-plugins-official":true},"permissions":{"deny":["Bash(git checkout:*)"]},"env":{"CLAUDE_CODE_COORDINATOR_MODE":"0"}}' \
  --append-system-prompt "$prompt" \
  "$start"
