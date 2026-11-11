// Who this aos belongs to, from environment variables (.env.local for the runner, watchdog and hooks; the Vercel
// project's env for the app). next.config.mjs copies the non-secret keys into the dashboard bundle, so this module
// stays free of Node APIs and works in client components too. Every value has a neutral default.
//
//   AOS_OWNER_NAME  the person aos works for, as prompts and the dashboard should call them (default: none)
//   AOS_OWNERS      comma-separated task owners; the first one that is not "claude" is you (default "me,claude")

/** The owner for tasks Claude does on its own. Always allowed. */
export const AI_OWNER = 'claude'

/** Owner keys are short lowercase slugs; the database check (migration 20261111120000) uses the same rule. */
export const OWNER_RE = /^[a-z][a-z0-9_-]{0,39}$/

export const DEFAULT_OWNERS = 'me,claude'

/** Parses AOS_OWNERS. Invalid entries are dropped, a human owner and "claude" are always present, order is kept. */
export const parseOwners = (raw: string | undefined): string[] => {
  const list = (raw ?? '')
    .split(',')
    .map((s) => s.trim().toLowerCase())
    .filter((s) => OWNER_RE.test(s))
  const uniq = [...new Set(list)]
  if (!uniq.some((o) => o !== AI_OWNER)) uniq.unshift('me')
  if (!uniq.includes(AI_OWNER)) uniq.push(AI_OWNER)
  return uniq
}

/** You: the first owner in the list that is not Claude. */
export const selfOf = (owners: string[]): string => owners.find((o) => o !== AI_OWNER) ?? 'me'

/** The name prompts use, or a neutral stand-in. */
export const personOf = (name: string | undefined, fallback = 'the user'): string => name?.trim() || fallback

// process.env.X is written out in full on purpose: Next.js replaces these exact expressions at build time.
export const owners = (): string[] => parseOwners(process.env.AOS_OWNERS || DEFAULT_OWNERS)
export const selfOwner = (): string => selfOf(owners())
export const ownerName = (): string => (process.env.AOS_OWNER_NAME ?? '').trim()
/** AOS_OWNER_NAME when set (e.g. "Alex"), else "the user". For prompts and messages. */
export const person = (): string => personOf(process.env.AOS_OWNER_NAME)
export const isOwner = (o: string): boolean => owners().includes(o)
