// Claude login state: one shared "logged out since" file for this machine (the runner, the Discord agent and every
// session use the same account), so a logged-out Claude is reported on Discord instead of failing silently in a
// terminal nobody watches. 11 Nov: a DM arrived, the agent printed "Login reached its time limit · Please run /login"
// in tmux, and nobody heard about it.
import { spawnSync } from 'node:child_process'
import { existsSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const STATE = join(import.meta.dirname, '..', 'runner', '.claude-auth.json')

/** Warn this long before the stored login expires (claude.ai logins last about 28 days). */
export const EXPIRY_WARN_MS = 48 * 3_600_000

// What Claude Code prints when it cannot authenticate. Matched on one short line near the bottom of a screen, or on a
// failed run's result, never on ordinary text.
const AUTH_RE =
  /please run \/login|login reached its time limit|oauth token (?:has )?expired|invalid api key|authentication_error|not logged in/i

/** True when this short text is a Claude Code login error. */
export const isAuthError = (text: string): boolean => text.length <= 300 && AUTH_RE.test(text)

/** A login error banner near the bottom of a Claude screen (not the same words inside a long reply). */
export const authErrorOnScreen = (screen: string): string | null => {
  const tail = screen.split('\n').map((l) => l.trim()).filter(Boolean).slice(-10)
  return tail.reverse().find(isAuthError) ?? null
}

export interface AuthStatus {
  loggedIn: boolean
  /** When the stored login expires, if Claude Code reports it. */
  expiresAt: Date | null
}

/** Pure part of readAuth, for tests. Unknown output counts as logged in: never raise an alarm on a parse problem. */
export const parseAuthStatus = (json: string, now: Date = new Date()): AuthStatus => {
  try {
    const s = JSON.parse(json) as { loggedIn?: boolean; loginExpiresAt?: string }
    const expiresAt = s.loginExpiresAt ? new Date(s.loginExpiresAt) : null
    const valid = expiresAt && !Number.isNaN(expiresAt.getTime()) ? expiresAt : null
    return { loggedIn: s.loggedIn !== false && !(valid && valid.getTime() <= now.getTime()), expiresAt: valid }
  } catch {
    return { loggedIn: true, expiresAt: null }
  }
}

/** `claude auth status --json`: local, no tokens. null when the CLI could not be run. */
export const readAuth = (now: Date = new Date()): AuthStatus | null => {
  const r = spawnSync('claude', ['auth', 'status', '--json'], { encoding: 'utf8', timeout: 20_000 })
  if (r.error || !r.stdout?.trim()) return null
  return parseAuthStatus(r.stdout, now)
}

export interface AuthState {
  /** ISO time the logout was first seen. */
  since: string
  /** Who saw it: 'runner' | 'agent' | 'status'. */
  source: string
  /** The line Claude printed, if any. */
  line?: string
  /** Discord message id of the 🔴 alert, once aos-watch has sent it. */
  alertId?: string
}

export const readAuthState = (): AuthState | null => {
  try {
    return existsSync(STATE) ? (JSON.parse(readFileSync(STATE, 'utf8')) as AuthState) : null
  } catch {
    return null
  }
}

export const writeAuthState = (s: AuthState | null): void => {
  if (s) writeFileSync(STATE, JSON.stringify(s))
  else if (existsSync(STATE)) unlinkSync(STATE)
}

/** The steps to log in again, in one place so the runner and the watchdog say the same thing. */
export const LOGIN_HOWTO =
  'Log in once on the PC and every session picks it up: in any terminal run `claude auth login` ' +
  '(or `/login` inside a Claude session). From the phone: VNC over Tailscale, open a terminal, same command.'
