// bun test runner/claude-auth.test.ts  (lives in runner/ because bun:test types are outside the Next type-check)
import { describe, expect, it } from 'bun:test'
import { authErrorOnScreen, isAuthError, parseAuthStatus } from '../lib/claude-auth'

const NOW = new Date('2026-11-11T22:00:00+05:30')

describe('isAuthError', () => {
  it('reads the lines Claude Code prints when logged out', () => {
    for (const line of [
      'Login reached its time limit · Please run /login',
      'API Error: 401 {"type":"error","error":{"type":"authentication_error","message":"OAuth token has expired."}}',
      'Invalid API key · Please run /login',
      'Not logged in · Please run /login',
    ]) expect(isAuthError(line)).toBe(true)
  })

  it('ignores ordinary text and long replies that mention login', () => {
    expect(isAuthError('Posted to LinkedIn; the login page did not appear')).toBe(false)
    expect(isAuthError(`${'x'.repeat(300)} please run /login`)).toBe(false)
  })
})

describe('authErrorOnScreen', () => {
  const screen = (tail: string[]): string => ['● earlier reply', ...Array(30).fill(''), ...tail].join('\n')

  it('finds the banner near the bottom', () => {
    expect(authErrorOnScreen(screen(['> hi', '  ⎿  Login reached its time limit · Please run /login', '─'.repeat(40), '❯ '])))
      .toBe('⎿  Login reached its time limit · Please run /login')
  })

  it('does not see one scrolled far up', () => {
    const lines = ['Please run /login', ...Array.from({ length: 20 }, (_, i) => `line ${i}`)]
    expect(authErrorOnScreen(lines.join('\n'))).toBeNull()
  })
})

describe('parseAuthStatus', () => {
  it('logged in with an expiry', () => {
    const s = parseAuthStatus('{"loggedIn":true,"loginExpiresAt":"2026-12-09T16:36:30.399Z"}', NOW)
    expect(s.loggedIn).toBe(true)
    expect(s.expiresAt?.toISOString()).toBe('2026-12-09T16:36:30.399Z')
  })

  it('an expiry in the past is logged out', () => {
    expect(parseAuthStatus('{"loggedIn":true,"loginExpiresAt":"2026-11-11T10:00:00Z"}', NOW).loggedIn).toBe(false)
  })

  it('loggedIn false is logged out', () => {
    expect(parseAuthStatus('{"loggedIn":false}', NOW)).toEqual({ loggedIn: false, expiresAt: null })
  })

  it('output it cannot read never raises an alarm', () => {
    expect(parseAuthStatus('not json', NOW).loggedIn).toBe(true)
    expect(parseAuthStatus('{"loggedIn":true,"loginExpiresAt":"soon"}', NOW)).toEqual({ loggedIn: true, expiresAt: null })
  })
})
