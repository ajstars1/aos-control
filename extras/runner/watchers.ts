// Extra (extras/README.md), runs only with AOS_EXTRA_WATCHERS=1.
// Cheap business watchers (no Claude run): every 30 min, ask a business's own read-only script what is new and ping
// Discord only when something happened. The script is `scripts/watch.py <since ISO>` in AOS_WATCHERS_DIR; it prints
// one JSON object shaped like WatchReport (built for a WhatsApp booking bot on Firestore). Messages are labelled
// with AOS_WATCHERS_LABEL.
import { spawnSync } from 'node:child_process'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { expandHome } from '../../lib/paths'

const EVERY_MS = 30 * 60 * 1000
// State stays in runner/ (gitignored), where it lived before the move to extras/.
const STATE = join(import.meta.dir, '..', '..', 'runner', '.watch-state.json')
const DIR = expandHome(process.env.AOS_WATCHERS_DIR ?? '')
const LABEL = process.env.AOS_WATCHERS_LABEL || 'shop'

type State = { since?: string; lastRun?: number; waitingKey?: string; failedKey?: string }
type WatchReport = {
  new_customers: string[]
  new_bookings: string[]
  inbound: number
  failed_sends: string[]
  failed_count: number
  waiting_reply: string[]
}

const load = (): State => (existsSync(STATE) ? (JSON.parse(readFileSync(STATE, 'utf8')) as State) : {})

const watch = (since: string): WatchReport => {
  const r = spawnSync('uv', ['run', '-q', '--with', 'google-cloud-firestore', 'python', '-I', 'scripts/watch.py', since],
    { cwd: DIR, encoding: 'utf8', timeout: 120_000 })
  if (r.status !== 0) throw new Error(`${LABEL} watch failed: ${(r.stderr || '').trim().slice(-200)}`)
  return JSON.parse(r.stdout) as WatchReport
}

/** Returns Discord lines to send (empty when nothing new). */
export const runWatchers = (): string[] => {
  if (!DIR) throw new Error('AOS_EXTRA_WATCHERS is on but AOS_WATCHERS_DIR is not set')
  const state = load()
  const now = Date.now()
  if (state.lastRun && now - state.lastRun < EVERY_MS) return []
  const since = state.since ?? new Date(now).toISOString() // first run: start watching from now, no backlog
  const lines: string[] = []
  const g = watch(since)
  if (g.new_bookings.length) lines.push(`🧵 **${LABEL} booking${g.new_bookings.length > 1 ? 's' : ''}**: ${g.new_bookings.join('; ')}`)
  if (g.new_customers.length) lines.push(`🧵 ${LABEL} new lead${g.new_customers.length > 1 ? 's' : ''}: ${g.new_customers.join('; ')}`)
  const failedKey = g.failed_sends.join('|')
  if (g.failed_count && failedKey !== state.failedKey) {
    lines.push(`⚠️ ${LABEL}: ${g.failed_count} WhatsApp message(s) failed to deliver: ${g.failed_sends.join('; ')}`)
  }
  const waitingKey = g.waiting_reply.join('|')
  if (g.waiting_reply.length && waitingKey !== state.waitingKey) {
    lines.push(`💬 ${LABEL} chats waiting for a human reply: ${g.waiting_reply.join(', ')}`)
  }
  writeFileSync(STATE, JSON.stringify({
    since: new Date(now).toISOString(), lastRun: now,
    waitingKey, failedKey: g.failed_count ? failedKey : state.failedKey,
  } satisfies State))
  return lines
}
