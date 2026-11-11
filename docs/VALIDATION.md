# Validation

Two kinds of evidence, kept apart on purpose. "Automated" means a command checked it. "Live" means someone saw it work end to end on the real machine. Nothing moves to "live verified" without a date and what was seen. (Format borrowed from github.com/govijr/terminal-mac.)

## Automated checks

Run on 4 Nov 2026, Ubuntu 26.04, Hyprland 0.53.3, kitty 0.45.0, bun 1.3.13:

| Check | Command | Result |
|---|---|---|
| Runner unit tests (send gate, spawn caps, preflight, run results, Discord, Claude limit) | `bun test runner/` | 59 pass, 0 fail |
| Installer plan changes nothing | `bash install.sh --plan`, compare `~/.claude/settings.json` mtime and `~/.config/systemd/user` listing before and after | unchanged |
| Installer health check | `bash install.sh doctor` | all required checks pass, exit 0 |
| desk MCP loads, 27 tools; new `screenshot` flag on click, move_pointer, drag, scroll, type_text, key, paste; `desk_done` | load `desk/server.py` with `uv run --with 'mcp>=2,<3' --with evdev` and list tools | as expected |
| desk badge file written atomically with `tool` and `until` | call `_acting()` directly | `{"tool": ..., "until": <epoch>}` |
| desk split geometry | `_place_beside` with a stubbed dispatcher | right half 683,28 681x738 for a 1362x738 window at 2,28 |
| live view uploads only changed frames, heartbeat caption, idle stop | `live.py` with mocked capture and Discord | first frame, one upload per change, caption-only heartbeat, ends "no change for N min" |
| Installer is portable (11 Nov) | fresh clone in a temp dir, `env -i HOME=$(mktemp -d) PATH=<temp bin with bun, node, claude, tmux symlinks>:/usr/bin:/bin bash install.sh --plan --discord --rc --vnc --agent-desk`, then `doctor` | every rendered path points at the temp clone, temp HOME or temp bin; no maintainer paths; nothing written |
| Config and owners (11 Nov) | `bun test runner/` (`runner/config.test.ts`) | owners, owner name, ventures, work dir, extras flags |
| desk plugin manifest | `claude plugin validate desk/` | passed (warning: no icon) |

## Live checks

| Check | Status |
|---|---|
| `terminal_open(beside=..., side="right")` splits a real window in half | **verified 4 Nov**: two test kitty windows at 2,28 and 683,28, both 681x738, then closed |
| Smoke test: MCP + Chrome + self-close | verified 28 Oct (README, about $0.92) |
| desk mouse, keys and screenshots on the real desktop | verified 28 Oct |
| `screenshot=true` on an action returns a fresh, correct screenshot | not yet verified live |
| Screen tools fail fast with the unlock message while hyprlock is up | not yet verified live (needs a locked screen) |
| sotto top bar shows the "agent is acting" badge and hides it when `until` passes | **verified 4 Nov**: after a waybar reload, "● claude" showed in ochre left of CPU with an 8 s `until`, and was gone in a screenshot 9.5 s later |
| badge cleared at once by `desk_done` | not yet verified live (same file delete path as the expiry test) |
| live view in #aos skips unchanged frames and ends after 10 idle minutes | not yet verified live (needs a Discord run) |
| Agent desktop: Chrome in headless cage shows a page, click + type land there, the user's pointer unmoved | **verified 4 Nov**: `~/.cache/aos-desk/agent-20261104-183113-545.png` shows the typed text in the input and the echo line; `hyprctl cursorpos` 756,654 before and after |
| Agent desktop guard refuses the real session (Hyprland pid, wayland-1, aos-vnc wayvnc) | verified 4 Nov with poisoned state files |
| kitty viewer `desk/view.py` (shm transport, idle = no redraw) | verified 4 Nov in a second headless kitty; `test_view.py` 6 pass, 2 pty tests need `AOS_VIEW_TEST_DISPLAY` |
| Agent desktop while the real screen is locked | not yet verified |
| Boot auto-login, lock first, bot and VNC come back after reboot | see `extras/README.md`; re-verify after any boot change |
| aos-unlock one-time codes and auto relock | see `extras/boot/unlock/`; re-verify after changes |
