# Architecture

aos control is a small control plane for one person and their Claude Code: one task list and calendar, an agent on a Linux machine that works through it, and a phone channel (Discord) to talk to it. This page is the detailed map. Setup lives in the [README](../README.md).

```
phone (Discord DM)   ─►  aos-discord: Claude Code session in tmux (Discord channel plugin) ──┐
phone (Claude app)   ─►  claude-rc: Remote Control server, spawns sessions (optional) ───────┤
systemd timer 10 min ─►  runner/tick.ts: pings overdue, runs one due `auto` task ────────────┼─► aos MCP (Vercel) ─► Supabase
any Claude session   ─►  desk MCP (local, optional): windows, kitty terminals, screen + mouse │
every Claude session ─►  SessionStart hook prints today's agenda ───────────────────────────┘          │
aos-watch (no AI)    ─►  permission prompts, restarts, approval cards, limit / logout fallback        │
Vercel cron daily    ─►  morning digest to the Discord webhook ◄───────────────────────────────────────┘
```

## Pieces

### aos MCP server (`app/api/mcp/route.ts`, on Vercel)

`https://<your-app>.vercel.app/api/mcp`, bearer token `AOS_MCP_TOKEN`. Registered in Claude Code at user scope as `aos`.

Tools: `agenda`, `task_list`, `task_add`, `task_update`, `task_done` (handles recurrence), `task_delete` (soft), `approval_request`, `approval_list`, `approval_decide`, `approval_mark_sent`, `log_activity`, `activity_recent`, `event_add`, `runs_recent`.

Owners are validated against `AOS_OWNERS`; the venture field lists the configured ventures.

### Dashboard (`/dashboard`, same Vercel app)

Phone-first, bottom tabs. The only write is approve or reject on a pending draft (two taps each, the same `decideApproval` as Discord `yes N`).

- **Today:** a one-line brief, what needs you, drafts waiting for your yes, what aos did today, ventures, goals.
- **Tasks:** filters for when, who, state, venture and search, applied in the browser and kept in the URL.
- **Ventures:** one page each: goals with pace, tasks, outreach, drafts, runs.
- **Story:** everything since day one plus copyable lines for posts (cached 30 min).
- **Log:** outreach, runs, drafts.

Login at `/login` checks `AOS_DASHBOARD_PASSCODE` (8+ characters) and sets a 30-day httpOnly HMAC-signed cookie. Five wrong tries per IP in 15 minutes lock that IP out (table `login_attempts`, IPs stored as an HMAC, fails closed). No polling: one server render per page visit, so the Vercel free tier is enough.

### Database (Supabase)

Tables: `tasks`, `runs`, `approvals`, `events`, `activity`, `touches`, `login_attempts`, plus the design tables of the proactive layer (`docs/proactive.md`, not wired yet). RLS on with no policies: only the service role (the Vercel app and your PC) can read or write. Deletes are soft (`deleted_at`). Migrations in `supabase/migrations/`.

### Runner (`runner/tick.ts`, systemd user timer every 10 minutes)

One tick:

1. Pings Discord about overdue tasks owned by people (08:00 to 22:00, once per about 20 hours each).
2. Picks one due `auto` task owned by `claude` (`lib/task-priority.ts`: a reply in a live conversation first, then other sends, then the rest, each by due time).
3. Runs the checks below, then starts `claude -p` headless in the task's folder (`cwd`, else `AOS_WORKDIR`) with hard caps.
4. Settles the task from what the run reported, posts the summary to Discord.

Checks before a spawn, cheapest first, none of them uses tokens:

- **Usage limit and login state** (`lib/claude-limit.ts`, `lib/claude-auth.ts`): shared files for this machine. At the limit, due tasks wait for the reset. Logged out, nothing spawns until the login is back.
- **Run budget** (`lib/run-budget.ts`): at most `AOS_RUNNER_MAX_RUNS_5H` runs (default 10) and `AOS_RUNNER_MAX_USD_5H` dollars (default 15) in any 5 hours, so your own sessions keep headroom.
- **Scheduled sends:** an approval with `send_after` in the future moves the task to that time.
- **Preflight** (`runner/preflight.ts`): Chrome and the Claude extension up (unless `AOS_RUNNER_CHROME=0`), Gmail or LinkedIn logged in when the task needs them (cookie names and expiry only, never values). A block is recorded as a `skipped` run; the second identical block in a row pauses the task.
- **Send gate** (`lib/send-gate.ts`), for `SEND APPROVED #N` tasks: see Safety in the README.

Caps per spawn (`runner/spawn.ts`), enforced by CLI flags:

| Kind | Max turns | Max spend |
|---|---|---|
| approved send | 15 | $1 |
| LinkedIn post send | 30 | $2 |
| check | 25 | $2 |
| task | 60 | $5 |

Every spawn also gets `--strict-mcp-config` with only `aos` (and `pilot-browser` if you have it), `--disallowedTools mcp__desk` (unattended runs never touch your screen), Sonnet unless the task prompt asks for Opus, and a system prompt with the house rules (never send, never buy or delete, read `CLAUDE.md` and `AOS_RUNNER_READ`).

Outcome (`lib/run-result.ts`): exit code 0 alone is not success. The run must call `task_done` or end with an `AOS_RESULT {"status": ...}` line; otherwise it counts as unverified and the task is retried later. Three spawned runs in a row without a result pause the task.

### Phone agent (`systemd/aos-discord.service`, `systemd/discord-agent.sh`)

A Claude Code session in the tmux session `aos-discord`, with the official Discord channel plugin enabled for this session only (it is disabled at user scope so other sessions do not log in as the bot). Its system prompt is `systemd/discord-agent.md`, filled in with `AOS_OWNER_NAME`, `AOS_OWNERS`, `AOS_WORKDIR` and `AOS_RUNNER_READ`, plus `AOS_AGENT_PROMPT_EXTRA` if you set one. Check it with `bash systemd/discord-agent.sh --print-prompt`.

A restart resumes the same conversation; `aos-discord-fresh.timer` starts a new one daily at 04:00. Every start first answers your DMs that arrived while it was down.

Watch it: `tmux attach -t aos-discord` (detach with Ctrl+b d).

### aos-watch (`watchdog/aos-watch.ts`, plain logic, no AI)

Every 10 seconds it reads the agent's tmux screen:

- A permission prompt that sits there for 45 seconds goes to your DM with the full command. ✅ answers yes, ❌ no, no answer in 30 minutes answers no so the session never stays frozen.
- No Claude process in the session: restart it, at most 3 times an hour, and say so.
- Pending approvals become DM cards with ✅/❌. The card follows the draft to sent or failed. Reminders at 13:00 and 19:00.
- **Usage limit:** seen on the agent's screen or reported by the runner. Your DMs are answered here: commands directly, anything else by Gemini (marked 🌐) if you configured `GEMINI_API_KEY` or `VERTEX_PROJECT`; real work is queued as a Claude task for just after the reset. After the reset, stalled sessions are told to continue.
- **Logged out:** seen on screen or in `claude auth status` (every 5 minutes). A 🔴 DM with the fix, the same fallback meanwhile, and the agent is told to catch up once you log in. 48 hours before the stored login expires it warns once a day.

### desk MCP (`desk/server.py`, optional, Hyprland only)

Live control of your Hyprland desktop, cheapest rung first: `windows` / `open_app` / `close_windows` / `focus_window` (hyprctl), then `terminal_open` / `terminal_send` / `terminal_read` / `terminal_key` (kitty remote control, reads text without screenshots), then `claude_session` (a visible Claude in kitty with Remote Control and a Stop hook that pings Discord), then `screenshot` + `click` / `type_text` / `key` / `scroll` / `drag` / `paste` (a virtual uinput mouse and keyboard, US layout; /dev/uinput must be writable for your seat user). Also `power`, `desk_status`, `wake_screen`, `stay_awake`, `live_start` / `live_stop` (a Discord message whose screenshot refreshes every few seconds, no tokens). Does nothing useful on a locked screen. Screenshots go to `~/.cache/aos-desk/` (last 30).

Bare folder names (`terminal_open("myproject")`) are looked up under `AOS_WORKDIR`, `~/Developer` and `~`. Settings come from `desk/aosconf.py`.

Packaged as a Claude Code plugin in `desk/.claude-plugin` with the `desk` skill.

### Agent desktop (`desk/agent_desk_server.py`, MCP `agentdesk`, optional)

A separate headless Wayland desktop (cage + wayvnc on 127.0.0.1:5910/5911) where agents run Chrome or kitty without moving your pointer, also while your screen is locked. One window at a time. Watch it with `python3 desk/view.py` in kitty. Service `aos-agent-desk.service` (`install.sh --agent-desk`, enabled but not started).

### Remote Control (`systemd/claude-rc.service`, optional)

`claude remote-control` so the machine shows up in the Claude phone app under Code (`AOS_RC_NAME`, default `linux`). Needs one interactive first run to answer its prompts: `claude remote-control --name linux`, answer y, Ctrl+C, then `bash install.sh --rc`.

### Remote desktop (`systemd/aos-vnc.service`, optional)

wayvnc bound to the Tailscale IP only, port 5900, no VNC password: every device in your tailnet can connect. Add a password before you share the tailnet.

## The sending rule

Unattended runs never send. They queue drafts with `approval_request`; Discord and the dashboard show them; you answer ✅ or `yes N`; an approved draft becomes a `SEND APPROVED #N` task that the runner sends word for word after the send gate passes.

## Recurrence

`daily`, `weekdays`, `weekly:MO,TH`, `every:3d`. Finishing a recurring task creates the next one.

## Configuration reference

| Key | Where | Default | What |
|---|---|---|---|
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | .env.local + Vercel | none | Database |
| `AOS_MCP_URL` | .env.local | none | Your app's `/api/mcp` |
| `AOS_MCP_TOKEN` | .env.local + Vercel | none | Bearer token for the MCP |
| `CRON_SECRET` | Vercel | none | Guards the daily digest route |
| `AOS_DASHBOARD_PASSCODE` | Vercel | none | Dashboard login (8+ characters) |
| `AOS_OWNER_NAME` | .env.local + Vercel | "the user" in prompts | Your name |
| `AOS_OWNERS` | .env.local + Vercel | `me,claude` | Task owners; first non-claude one is you |
| `AOS_VENTURES` / `config/ventures.json` | Vercel / repo | work, personal, general | Ventures for tasks and the dashboard |
| `AOS_WORKDIR` | .env.local | `$HOME` | Claude's working folder |
| `AOS_RUNNER_READ` | .env.local | none | Extra files the runner reads |
| `AOS_AGENT_PROMPT_EXTRA` | .env.local | none | Markdown appended to the phone agent's prompt |
| `AOS_RC_NAME` | .env.local | `linux` | Remote Control name |
| `DISCORD_WEBHOOK_URL` | .env.local + Vercel | none | Channel pings and the digest |
| `AOS_DM_CHANNEL` | .env.local | saved by the agent | Your DM channel id for desk session pings |
| `GEMINI_API_KEY` or `VERTEX_PROJECT`, `GEMINI_MODEL` | .env.local | none, `gemini-2.5-flash` | Fallback answers |
| `AOS_RUNNER_MAX_RUNS_5H`, `AOS_RUNNER_MAX_USD_5H` | .env.local | 10, 15 | Run budget |
| `AOS_RUNNER_CHROME` | .env.local | on | `0` starts runs without `--chrome` and skips the Chrome preflight |
| `AOS_STATE_DIR` | .env.local | `~/.local/state/aos` | Runner MCP config, notify fallback log |
| `AOS_CHROME_COOKIES` | .env.local | `~/.config/google-chrome/Default/Cookies` | Preflight login check |
| `AOS_EXTRA_*` | .env.local | off | [extras](../extras/README.md) |

Times are India Standard Time throughout (dates, the digest, reminders, `move N tomorrow`). A time zone setting is on the roadmap.

## State files (all gitignored)

`runner/.lock`, `.budget-note`, `.claude-limit.json`, `.claude-auth.json`, `watchdog/.approval-cards.json`, `.login-warned`, `~/.cache/aos/` (agent session id, DM channel id), `~/.local/state/aos/` (runner MCP config, notify fallback log), `~/.cache/aos-desk/` (screenshots, badge, live view).

## Run by hand

- `bun runner/tick.ts`: one tick (needs `.env.local`).
- `bun hooks/agenda.ts`: what the SessionStart hook prints.
- `bun runner/smoke.ts && bun runner/tick.ts`: end-to-end smoke test (MCP + Chrome + self-close, about $0.90 of usage).
- `bun test runner/` and `npx tsc --noEmit`: the checks CI runs.
- Deploy: `npx vercel deploy --prod` from the repo. The build needs TypeScript 6 (Next 15 cannot use TypeScript 7).
