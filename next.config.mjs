import { existsSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = dirname(fileURLToPath(import.meta.url))

// Ventures: the AOS_VENTURES env var (one-line JSON, for Vercel) wins, else config/ventures.json, else the built-in
// neutral list (lib/ventures.ts). Read once at build time and inlined, so the dashboard's client components see it.
const venturesFile = join(root, 'config', 'ventures.json')
const ventures = process.env.AOS_VENTURES || (existsSync(venturesFile) ? readFileSync(venturesFile, 'utf8') : '')

/** @type {import('next').NextConfig} */
const config = {
  poweredByHeader: false,
  outputFileTracingRoot: root,
  // Non-secret settings only: these end up in the browser bundle.
  env: {
    AOS_VENTURES: ventures,
    AOS_OWNERS: process.env.AOS_OWNERS ?? '',
    AOS_OWNER_NAME: process.env.AOS_OWNER_NAME ?? '',
  },
}

export default config
