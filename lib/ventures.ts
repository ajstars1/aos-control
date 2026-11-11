// Display metadata per venture (a project, client or area of life a task belongs to). The list comes from
// config/ventures.json (copy config/ventures.example.json; the real file is gitignored) or the AOS_VENTURES env var
// (the same JSON on one line, for Vercel). next.config.mjs reads either at build time into process.env.AOS_VENTURES,
// so this module needs no Node APIs and works in client components.
// Colors are the validated categorical slots (dark steps) in list order, so a venture keeps its color on every page;
// it is always shown next to its name, never alone.

export interface VentureMeta {
  key: string
  name: string
  blurb: string
  color: string
  /** Listed on the dashboard only when it has tasks or activity. */
  hidden: boolean
}

export const PALETTE = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9']
const FALLBACK = '#7b8494'

export const DEFAULT_VENTURES: VentureMeta[] = [
  { key: 'work', name: 'Work', blurb: 'Projects and clients', color: PALETTE[0]!, hidden: false },
  { key: 'personal', name: 'Personal', blurb: 'Life admin', color: PALETTE[1]!, hidden: false },
  { key: 'general', name: 'General', blurb: 'Everything else', color: PALETTE[2]!, hidden: false },
]

export const isVentureKey = (key: string): boolean => /^[a-z0-9_-]{1,40}$/i.test(key)

const HEX = /^#[0-9a-f]{6}$/i

/** Parses the ventures JSON (an array of {key, name?, blurb?, color?, hidden?}). Bad input gives the defaults. */
export const parseVentures = (raw: string | undefined): VentureMeta[] => {
  if (!raw?.trim()) return DEFAULT_VENTURES
  let data: unknown
  try {
    data = JSON.parse(raw)
  } catch {
    return DEFAULT_VENTURES
  }
  const list = Array.isArray(data) ? data : (data as { ventures?: unknown } | null)?.ventures
  if (!Array.isArray(list)) return DEFAULT_VENTURES
  const out: VentureMeta[] = []
  for (const item of list) {
    if (!item || typeof item !== 'object') continue
    const v = item as Record<string, unknown>
    const key = typeof v.key === 'string' ? v.key.trim() : ''
    if (!isVentureKey(key) || out.some((o) => o.key === key)) continue
    out.push({
      key,
      name: typeof v.name === 'string' && v.name.trim() ? v.name.trim().slice(0, 60) : key,
      blurb: typeof v.blurb === 'string' ? v.blurb.trim().slice(0, 120) : '',
      color: typeof v.color === 'string' && HEX.test(v.color) ? v.color : (PALETTE[out.length % PALETTE.length] ?? FALLBACK),
      hidden: v.hidden === true,
    })
  }
  return out.length ? out : DEFAULT_VENTURES
}

// Written out in full: Next.js inlines process.env.AOS_VENTURES at build time.
const KNOWN = parseVentures(process.env.AOS_VENTURES)

export const VENTURES: readonly VentureMeta[] = KNOWN

export const VENTURE_ORDER = KNOWN.map((v) => v.key)

/** Ventures always listed on the dashboard, even with nothing in them yet. */
export const SHOWN_VENTURES = KNOWN.filter((v) => !v.hidden).map((v) => v.key)

export const ventureMeta = (key: string): VentureMeta =>
  KNOWN.find((v) => v.key === key) ?? { key, name: key, blurb: '', color: FALLBACK, hidden: false }
