// Local paths and switches for the processes that run on your machine (runner, watchdog, hooks). Node APIs, so
// never import this from the dashboard.
//
//   AOS_WORKDIR  where Claude works: the runner's default cwd and the Discord agent's folder (default: $HOME)
//   AOS_EXTRA_*  optional add-ons for one specific hardware setup (extras/), all off unless set to 1
import { homedir } from 'node:os'
import { join, resolve } from 'node:path'

type Env = Record<string, string | undefined>

/** This checkout, wherever it was cloned. */
export const REPO_DIR = resolve(import.meta.dirname, '..')

export const expandHome = (p: string): string => (p === '~' ? homedir() : p.startsWith('~/') ? join(homedir(), p.slice(2)) : p)

export const workDir = (env: Env = process.env): string => {
  const raw = env.AOS_WORKDIR?.trim()
  return raw ? resolve(expandHome(raw)) : homedir()
}

/** Unattended runs get Chrome (Claude in Chrome) unless AOS_RUNNER_CHROME is 0 / false / off. */
export const runnerChrome = (env: Env = process.env): boolean => !/^(?:0|false|no|off)$/i.test(env.AOS_RUNNER_CHROME?.trim() ?? '')

/** Optional extras (extras/README.md) run only when their flag is "1" or "true". */
export const extraOn = (flag: string, env: Env = process.env): boolean => /^(?:1|true|yes|on)$/i.test(env[flag]?.trim() ?? '')
