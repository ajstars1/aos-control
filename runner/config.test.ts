import { afterEach, describe, expect, test } from 'bun:test'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { homedir } from 'node:os'
import { AI_OWNER, OWNER_RE, isOwner, owners, ownerName, parseOwners, person, personOf, selfOf, selfOwner } from '../lib/config'
import { DEFAULT_VENTURES, PALETTE, parseVentures } from '../lib/ventures'
import { expandHome, extraOn, REPO_DIR, runnerChrome, workDir } from '../lib/paths'

const saved = { ...process.env }
afterEach(() => {
  for (const k of ['AOS_OWNERS', 'AOS_OWNER_NAME', 'AOS_WORKDIR']) {
    if (saved[k] === undefined) delete process.env[k]
    else process.env[k] = saved[k]
  }
})

describe('owners', () => {
  test('default is "me" plus claude', () => {
    expect(parseOwners(undefined)).toEqual(['me', 'claude'])
    expect(parseOwners('')).toEqual(['me', 'claude'])
  })

  test('keeps order, lowercases, drops bad entries and duplicates', () => {
    expect(parseOwners(' Alex, claude ,sam,alex,Bad Name,,x'.trim())).toEqual(['alex', 'claude', 'sam', 'x'])
  })

  test('always has a human owner and claude', () => {
    expect(parseOwners('claude')).toEqual(['me', 'claude'])
    expect(parseOwners('alex')).toEqual(['alex', 'claude'])
  })

  test('the first human owner is you', () => {
    expect(selfOf(['claude', 'alex', 'sam'])).toBe('alex')
    expect(selfOf(parseOwners('alex,claude,sam,family'))).toBe('alex')
  })

  test('reads AOS_OWNERS from the environment', () => {
    process.env.AOS_OWNERS = 'alex,claude,sam'
    expect(owners()).toEqual(['alex', 'claude', 'sam'])
    expect(selfOwner()).toBe('alex')
    expect(isOwner('sam')).toBe(true)
    expect(isOwner('me')).toBe(false)
    expect(isOwner(AI_OWNER)).toBe(true)
    delete process.env.AOS_OWNERS
    expect(owners()).toEqual(['me', 'claude'])
  })

  test('the database check uses the same rule as the app', () => {
    const sql = readFileSync(join(import.meta.dir, '..', 'supabase', 'migrations', '20261111120000_owners.sql'), 'utf8')
    const m = /owner ~ '([^']+)'/.exec(sql)
    expect(m?.[1]).toBe(OWNER_RE.source)
    // every owner an existing install may already have stays valid
    for (const o of ['me', 'claude', 'alex', 'family', 'team-2']) expect(OWNER_RE.test(o)).toBe(true)
    for (const o of ['', 'Alex', '1x', 'a b', 'x'.repeat(41)]) expect(OWNER_RE.test(o)).toBe(false)
  })
})

describe('owner name', () => {
  test('falls back to a neutral word', () => {
    expect(personOf(undefined)).toBe('the user')
    expect(personOf('  ')).toBe('the user')
    expect(personOf('Alex')).toBe('Alex')
  })

  test('reads AOS_OWNER_NAME', () => {
    delete process.env.AOS_OWNER_NAME
    expect(ownerName()).toBe('')
    expect(person()).toBe('the user')
    process.env.AOS_OWNER_NAME = ' Alex '
    expect(ownerName()).toBe('Alex')
    expect(person()).toBe('Alex')
  })
})

describe('ventures', () => {
  test('missing or broken config gives the neutral defaults', () => {
    expect(parseVentures(undefined)).toEqual(DEFAULT_VENTURES)
    expect(parseVentures('not json')).toEqual(DEFAULT_VENTURES)
    expect(parseVentures('{"a":1}')).toEqual(DEFAULT_VENTURES)
    expect(parseVentures('[]')).toEqual(DEFAULT_VENTURES)
  })

  test('fills names and colors, keeps hidden, drops bad keys and duplicates', () => {
    const v = parseVentures(JSON.stringify([
      { key: 'shop', name: 'The Shop', blurb: 'Retail', color: '#112233' },
      { key: 'blog' },
      { key: 'bad key!' },
      { key: 'shop', name: 'again' },
      { key: 'old', hidden: true, color: 'red' },
    ]))
    expect(v.map((x) => x.key)).toEqual(['shop', 'blog', 'old'])
    expect(v[0]).toEqual({ key: 'shop', name: 'The Shop', blurb: 'Retail', color: '#112233', hidden: false })
    expect(v[1]).toEqual({ key: 'blog', name: 'blog', blurb: '', color: PALETTE[1]!, hidden: false })
    expect(v[2]!.hidden).toBe(true)
    expect(v[2]!.color).toBe(PALETTE[2]!)
  })

  test('accepts {"ventures": [...]} too', () => {
    expect(parseVentures('{"ventures":[{"key":"x"}]}').map((v) => v.key)).toEqual(['x'])
  })

  test('the committed example parses', () => {
    const raw = readFileSync(join(import.meta.dir, '..', 'config', 'ventures.example.json'), 'utf8')
    const v = parseVentures(raw)
    expect(v.length).toBeGreaterThan(2)
    expect(v).not.toEqual(DEFAULT_VENTURES)
  })
})

describe('paths', () => {
  test('repo dir is this checkout', () => {
    expect(REPO_DIR).toBe(join(import.meta.dir, '..'))
  })

  test('work dir defaults to $HOME and expands ~', () => {
    expect(workDir({})).toBe(homedir())
    expect(workDir({ AOS_WORKDIR: '' })).toBe(homedir())
    expect(workDir({ AOS_WORKDIR: '~/code' })).toBe(join(homedir(), 'code'))
    expect(workDir({ AOS_WORKDIR: '/srv/work' })).toBe('/srv/work')
    expect(expandHome('~')).toBe(homedir())
  })

  test('the runner uses Chrome unless switched off', () => {
    expect(runnerChrome({})).toBe(true)
    expect(runnerChrome({ AOS_RUNNER_CHROME: '1' })).toBe(true)
    expect(runnerChrome({ AOS_RUNNER_CHROME: '0' })).toBe(false)
    expect(runnerChrome({ AOS_RUNNER_CHROME: 'off' })).toBe(false)
  })

  test('extras are off unless the flag is exactly on', () => {
    expect(extraOn('AOS_EXTRA_WATCHERS', {})).toBe(false)
    expect(extraOn('AOS_EXTRA_WATCHERS', { AOS_EXTRA_WATCHERS: '0' })).toBe(false)
    expect(extraOn('AOS_EXTRA_WATCHERS', { AOS_EXTRA_WATCHERS: 'false' })).toBe(false)
    expect(extraOn('AOS_EXTRA_WATCHERS', { AOS_EXTRA_WATCHERS: '1' })).toBe(true)
    expect(extraOn('AOS_EXTRA_WATCHERS', { AOS_EXTRA_WATCHERS: 'true' })).toBe(true)
  })
})
