// Your day as JSON for a desktop widget (the sotto wallpaper's "Today" column reads it).
// Run: cd <repo> && bun hooks/today-json.ts   (Bun loads .env.local from cwd)
// Output: {"items": [{"when", "title", "flag"}], "footer"}; contract in sotto/sotto/today.py.
// Shows what a person has to do (owner is not claude): calendar first, then today, then overdue.
import { selfOwner } from '../lib/config'
import { agenda } from '../lib/tasks'

interface Item {
  when: string
  title: string
  flag: 'overdue' | 'today' | 'event' | ''
}

const MAX = 9
const IST = 'Asia/Kolkata'
const hm = (iso: string): string =>
  new Intl.DateTimeFormat('en-GB', { timeZone: IST, hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(iso))
const day = (iso: string): string =>
  new Intl.DateTimeFormat('en-GB', { timeZone: IST, day: 'numeric', month: 'short' }).format(new Date(iso))
const who = (owner: string | null | undefined): string => (owner && owner !== selfOwner() ? `${owner}: ` : '')

const timeout = setTimeout(() => {
  process.stderr.write('aos agenda timed out\n')
  process.exit(1)
}, 20_000)

try {
  const a = await agenda(2)
  const human = (t: { owner?: string | null }): boolean => t.owner !== 'claude'
  const todayKey = day(new Date().toISOString())
  const events: Item[] = a.events.slice(0, 3).map((e) => ({
    when: (day(e.starts_at) === todayKey ? '' : 'tmrw ') + hm(e.starts_at),
    title: e.title,
    flag: 'event',
  }))
  const today: Item[] = a.today.filter(human).map((t) => ({
    when: t.due_at ? hm(t.due_at) : 'today',
    title: `${who(t.owner)}${t.title}`,
    flag: 'today',
  }))
  const overdueAll = a.overdue.filter(human)
  const room = Math.max(0, MAX - events.length - today.length)
  const overdue: Item[] = overdueAll.slice(0, room).map((t) => ({
    when: t.due_at ? day(t.due_at) : '',
    title: `${who(t.owner)}${t.title}`,
    flag: 'overdue',
  }))
  const more = overdueAll.length - overdue.length
  const drafts = a.approvals.length
  const footer = [
    more > 0 ? `+${more} more overdue` : '',
    drafts > 0 ? `${drafts} draft${drafts === 1 ? '' : 's'} wait for your yes` : '',
  ]
    .filter(Boolean)
    .join(' · ')
  process.stdout.write(JSON.stringify({ items: [...events, ...today, ...overdue].slice(0, MAX), footer }))
  clearTimeout(timeout)
} catch (err) {
  process.stderr.write(`aos agenda failed: ${err instanceof Error ? err.message : String(err)}\n`)
  process.exit(1)
}
