# aos control

**Message your Linux PC from your phone, and a Claude agent does the work. It drafts anything outbound and sends nothing without your yes.**

[![CI](https://github.com/ajstars1/aos-control/actions/workflows/ci.yml/badge.svg)](https://github.com/ajstars1/aos-control/actions/workflows/ci.yml)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

aos control runs on your own Linux machine and your own Claude Code subscription. A small web app (free Vercel + free Supabase) holds one task list and calendar. Everything else runs locally as systemd user services.

- **Message your PC from your phone.** DM a Discord bot ("check if anyone replied to my email", "open a Claude session in myproject"). A Claude Code session on your PC does the work and answers in the DM.
- **One task list and calendar in every Claude session.** The `aos` MCP server gives any Claude Code session `agenda`, `task_add`, `task_done` and more. Each new session starts with today's agenda.
- **An unattended runner that drafts but never sends.** Every 10 minutes it starts Claude on one due task. Emails, DMs and posts come back as drafts for you to approve.
- **Approval cards with ✅ and ❌.** Drafts arrive in your Discord DM and on a phone-friendly dashboard. Tap ✅ and the runner sends that exact text.
- **A watchdog that tells you when Claude is stuck.** Frozen at a permission prompt, crashed, logged out or at its usage limit: you get a DM with the fix, and an optional Gemini fallback answers meanwhile.
- **Optional desktop control.** On Hyprland, Claude can open apps, drive kitty terminals, take screenshots and click, from your phone.

> **Status: early.** Linux only. Tested on Ubuntu with Hyprland. Times are India Standard Time for now. Expect rough edges.
> On a Mac, Windows or only a phone? Use the hosted version, [aos](https://github.com/ajstars1/aos).

## Requirements

- Linux with systemd (user services) and a desktop session.
- [Claude Code](https://docs.claude.com/en/docs/claude-code), logged in on a Pro or Max plan.
- [Bun](https://bun.sh) 1.3+, Node.js 22+, tmux, python3, curl.
- Free accounts: [Supabase](https://supabase.com), [Vercel](https://vercel.com). [Discord](https://discord.com) for the phone parts.
- Google Chrome with the Claude in Chrome extension. The runner checks for it before every run; set `AOS_RUNNER_CHROME=0` to run without a browser.
- Optional desk control: Hyprland, kitty, grim, wl-clipboard, [uv](https://docs.astral.sh/uv/).
- Optional remote desktop: wayvnc and Tailscale.

## Quick start

About 30 minutes. Each step is copy-pasteable; replace the `<...>` parts.

1. **Clone and install dependencies.**
   ```bash
   git clone https://github.com/ajstars1/aos-control.git ~/aos-control
   cd ~/aos-control && npm ci
   ```

2. **Create the database.** Make a free Supabase project, then push the schema:
   ```bash
   npx supabase login
   npx supabase link --project-ref <your-project-ref>
   npx supabase db push
   ```
   If the CLI asks for a config file, run `npx supabase init` first. You can also paste the files in `supabase/migrations/` into the SQL editor, in name order.

3. **Fill in your settings.** The first run of the installer creates `.env.local` from `.env.example` and stops:
   ```bash
   bash install.sh
   ```
   Fill in `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` (Supabase: Project settings, API), and make up `AOS_MCP_TOKEN`, `CRON_SECRET` and `AOS_DASHBOARD_PASSCODE` (`openssl rand -hex 32` for each). Set `AOS_OWNER_NAME` to your name. Optional: copy `config/ventures.example.json` to `config/ventures.json` and list your own projects.

4. **Deploy the MCP server and dashboard to Vercel.**
   ```bash
   npx vercel link
   for k in SUPABASE_URL SUPABASE_SERVICE_ROLE_KEY AOS_MCP_TOKEN CRON_SECRET AOS_DASHBOARD_PASSCODE AOS_OWNER_NAME; do
     npx vercel env add "$k" production
   done
   npx vercel deploy --prod
   ```
   Each `env add` asks for the value; paste it from `.env.local`. If you use your own ventures, also add `AOS_VENTURES` with the one-line JSON from `jq -c . config/ventures.json`. Put the deployed URL in `.env.local` as `AOS_MCP_URL=https://<your-app>.vercel.app/api/mcp`.

5. **Add the MCP server to Claude Code.**
   ```bash
   claude mcp add --scope user --transport http aos https://<your-app>.vercel.app/api/mcp \
     --header "Authorization: Bearer <AOS_MCP_TOKEN>"
   ```
   Optional desk control (Hyprland):
   ```bash
   claude mcp add --scope user desk -- uv run -q --script ~/aos-control/desk/server.py
   ```

6. **Switch on the runner.**
   ```bash
   bash install.sh --plan   # shows every step, changes nothing
   bash install.sh          # runner timer + agenda hook
   bash install.sh doctor   # health check
   ```

7. **Discord (optional, recommended).**
   - Make a private server with an `#aos` channel. Channel settings, Integrations, Webhooks, New, copy the URL into `.env.local` as `DISCORD_WEBHOOK_URL` and into Vercel (`npx vercel env add DISCORD_WEBHOOK_URL production`, then deploy again).
   - At discord.com/developers: New Application, Bot, turn on Message Content Intent, Reset Token. Invite the bot to your server (OAuth2, URL Generator, `bot` scope).
   - Install the Discord channel plugin and keep it off for normal sessions (the phone agent turns it on for itself):
     ```bash
     claude plugin install discord@claude-plugins-official
     claude plugin disable discord@claude-plugins-official
     ```
   - Save the bot token without it touching your shell history:
     ```bash
     mkdir -p ~/.claude/channels/discord
     read -rsp "bot token: " T && printf 'DISCORD_BOT_TOKEN=%s\n' "$T" > ~/.claude/channels/discord/.env && unset T
     chmod 600 ~/.claude/channels/discord/.env
     ```
   - Start the phone agent and the watchdog, then pair: DM the bot "hi", and send the code it gives you to the agent:
     ```bash
     bash install.sh --discord
     tmux send-keys -t aos-discord '/discord:access pair <code>' Enter
     tmux send-keys -t aos-discord '/discord:access policy allowlist' Enter
     ```
     Watch it with `tmux attach -t aos-discord` (detach with Ctrl+b d).

Optional: `bash install.sh --rc` for Claude Remote Control (run `claude remote-control --name linux` once by hand first and answer its prompts), `--vnc` for wayvnc over Tailscale.

## How it works

```
 your phone                      your Linux PC                                     the cloud (free tiers)
 ──────────                      ─────────────                                     ──────────────────────
 Discord DM ───────────────────► aos-discord: Claude Code in tmux ──────┐
   ▲  ✅/❌ cards, alerts          (Discord channel plugin)              │
   │                                                                     ├── aos MCP ──► Vercel app ──► Supabase
   ├──────────────────────────── aos-watch: prompts, restarts, cards ────┤              (MCP + dashboard)   (tasks, drafts,
   │                               limit / logout fallback (Gemini)      │                                   runs, activity)
   │                                                                     │
   └──── webhook pings ◄──────── runner: systemd timer, every 10 min ────┤
                                   claude -p on one due task, with caps  │
 dashboard (browser) ──────────────────────────────────────────────────────────────► same Vercel app
                                 any Claude session: aos MCP + agenda hook
                                 optional: desk MCP (Hyprland), Remote Control, VNC
```

Details, including every component and setting: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Safety model

The model is never the only thing between a draft and the outside world. These checks are plain code.

- **Approve to send.** Unattended runs may not send, post, comment or message. They call `approval_request`. Only your ✅, your `yes N`, or a tap on the dashboard approves a draft, and the runner then sends exactly that text.
- **Send gate.** Before an approved send starts, plain rules check the text: no unfilled placeholders (`{{first_name}}`, `[Company]`, TODO), no em dashes, a length cap per channel, at most two links, a real recipient (an email address for Gmail, a profile or thread for LinkedIn DMs). A note saying "hold" or "don't send" on the task or its parent stops it, even after approval. Each person gets at most two touches; a third is blocked.
- **Scheduled sends never go early.** A draft with a send time waits for it without starting Claude.
- **Spend caps per run.** Every unattended run has a turn cap and a dollar cap by CLI flag: $1 for a send, $2 for a check, $5 for a task. On top, at most 10 runs and $15 in any 5 hours (both configurable), so your own sessions keep headroom.
- **No done on exit 0.** A run counts as done only if it called `task_done` or printed an `AOS_RESULT` line. Three runs in a row without a result pause the task and tell you.
- **Preflight.** Before spending tokens the runner checks that Chrome and the extension are up and that Gmail or LinkedIn are logged in when the task needs them. Two identical failures in a row pause the task.
- **Narrow tools.** Unattended runs get only the `aos` MCP server (and pilot-browser if installed), and may not use the desk tools. The phone agent denies `git checkout` and anything your settings would only "ask" for.
- **Never buy, delete or log in.** The runner and agent prompts forbid purchases, deletes, account changes and typing credentials. Logins, CAPTCHAs and payments are handed back to you.

These rules lower the risk. They do not remove it: the agent works in your logged-in browser and your files. Read what it drafts before you approve.

## Real costs

- **Claude:** it uses your Claude Code subscription; there is no API key. Unattended runs use the same usage limits as your own sessions. A small task uses roughly what $0.50 to $1 of API usage would cost. Eight runs a day at that rate is a noticeable part of a Pro plan; a Max plan has more room. Leave tasks with `auto` off to keep them manual, and lower the 5-hour budget in `.env.local`.
- **When Claude hits its limit:** due tasks wait for the reset, and the watchdog tells you. Nothing retries in a loop.
- **Supabase, Vercel, Discord:** free tiers are enough. The dashboard does not poll, and the only cloud cron is one morning digest a day.
- **Gemini fallback:** optional. A free Google AI Studio key covers it.

## Commands you can send from Discord

| Message | What happens |
|---|---|
| `today` | Today's agenda: overdue, due today, calendar, drafts waiting |
| `yes 12` / `no 12` | Approve or drop draft #12 (or tap ✅ / ❌ on its card) |
| `edit 12: <new text>` | Approve draft #12 with your text instead |
| `show 12` | The full text of draft #12 |
| `done 7 [note]` / `skip 7` | Close task #7 |
| `move 7 tomorrow 10am` | Reschedule task #7 |
| `add call the accountant Fri 11am` | New task for you; say "you do it" to give it to Claude |
| `status` | Which aos services are running |
| `ss` | A screenshot of your screen (desk control) |
| `stream 10` / `stop stream` | A live screenshot in #aos for 10 minutes |
| `open kitty in myproject and run npm test` | Desktop actions (desk control) |
| `reboot` / `cancel reboot` | Power actions, with a confirmation step |
| anything else | A request: Claude does it on your PC and reports back |

## Optional extras

`extras/` holds add-ons built for one specific machine: Intel AMT and MeshCentral for remote power on, a MeshCentral firewall and backup job, boot auto-login into a locked screen, TOTP unlock from Discord, an always-on cloud bot, and a watcher for a small business's booking bot. They are off by default, and the runner never loads them unless you switch them on. See [extras/README.md](extras/README.md).

## Troubleshooting

Start with the health check. It is read-only and prints no secrets:

```bash
bash install.sh doctor
```

- **The runner does nothing.** `journalctl --user -u aos-tick -n 50`. Only tasks with owner `claude`, `auto` on and a due time in the past run, one per tick.
- **The Discord agent does not answer.** `tmux attach -t aos-discord` to see its screen. `journalctl --user -u aos-discord -u aos-watch -n 50`.
- **"Claude is logged out" DM.** Run `claude auth login` on the PC.
- **A task got paused.** Its notes say why (preflight, stall rule or send gate). Fix it, then turn `auto` back on.
- **Messages that could not reach Discord** are kept in `~/.local/state/aos/notify-fallback.log`.

## For testers

Thank you for trying it. Here is what to do in your first 30 minutes:

1. Run `bash install.sh doctor` and fix anything marked MISSING.
2. Open a new Claude Code session. It should start with an "aos agenda" block. Ask: "add a task to aos: buy milk, due today 6pm". Check it on the dashboard at `https://<your-app>.vercel.app`.
3. Run the smoke test. It adds a safe task for Claude and runs one tick: `bun runner/smoke.ts && bun runner/tick.ts`. Discord should get a ✅ with a short summary.
4. Try the approval flow. In a Claude session: "draft an email to <your own address> saying hello, and queue it with approval_request". Tap ✅ on the card. Within 10 minutes the runner sends it from your Gmail in Chrome.
5. DM the bot `today`, then a real request.

To report a problem, open a [GitHub issue](https://github.com/ajstars1/aos-control/issues) with:
- what you did and what you expected,
- the output of `bash install.sh doctor`,
- the last lines of `journalctl --user -u aos-tick -n 50` (read them first and remove anything private).

## Roadmap

- A time zone setting (today everything is India Standard Time).
- One-command setup for the Supabase and Vercel steps.
- Tests for the watchdog's Discord flows.
- The proactive layer: goals instead of commands ([design](docs/proactive.md)).

## License

[MIT](LICENSE). Built by Ayush Jamwal ([@ajstars1](https://github.com/ajstars1)).
