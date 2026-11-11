// Gemini, the fallback brain when Claude is at its usage limit or logged out (aos-watch answers Discord DMs with it).
// Optional. Two ways to reach it, the first one set wins:
//   GEMINI_API_KEY   a Google AI Studio key (free tier is enough): generativelanguage.googleapis.com
//   VERTEX_PROJECT   a GCP project with Vertex AI, through your own `gcloud` login on this PC (no key stored)
// The aos-cloud extra has its own copy with a service account (extras/cloud/bot.ts).
import { spawnSync } from 'node:child_process'

const API_KEY = process.env.GEMINI_API_KEY ?? ''
const PROJECT = process.env.VERTEX_PROJECT ?? ''
const MODEL = process.env.GEMINI_MODEL ?? 'gemini-2.5-flash'
const TOKEN_TTL_MS = 45 * 60_000

let token: { value: string; at: number } | null = null
const accessToken = (): string => {
  if (token && Date.now() - token.at < TOKEN_TTL_MS) return token.value
  const r = spawnSync('gcloud', ['auth', 'print-access-token'], { encoding: 'utf8', timeout: 30_000 })
  const value = (r.stdout ?? '').trim()
  if (r.status !== 0 || !value) throw new Error(`gcloud token: ${(r.stderr ?? '').trim().slice(-200) || 'no output'}`)
  token = { value, at: Date.now() }
  return value
}

type GeminiResponse = {
  candidates?: { content?: { parts?: { text?: string }[] } }[]
  error?: { message: string }
}

/** True when a Gemini fallback is configured. */
export const geminiConfigured = (): boolean => Boolean(API_KEY || PROJECT)

const endpoint = (): { url: string; headers: Record<string, string> } => {
  if (API_KEY) {
    return {
      url: `https://generativelanguage.googleapis.com/v1beta/models/${MODEL}:generateContent`,
      headers: { 'x-goog-api-key': API_KEY, 'Content-Type': 'application/json' },
    }
  }
  if (!PROJECT) throw new Error('no Gemini fallback: set GEMINI_API_KEY or VERTEX_PROJECT in .env.local')
  return {
    url: `https://aiplatform.googleapis.com/v1/projects/${PROJECT}/locations/global/publishers/google/models/${MODEL}:generateContent`,
    headers: { Authorization: `Bearer ${accessToken()}`, 'Content-Type': 'application/json' },
  }
}

export const gemini = async (prompt: string, system: string, json = false): Promise<string> => {
  const { url, headers } = endpoint()
  const res = await fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      systemInstruction: { parts: [{ text: system }] },
      contents: [{ role: 'user', parts: [{ text: prompt }] }],
      generationConfig: { maxOutputTokens: 1024, thinkingConfig: { thinkingBudget: 0 }, ...(json ? { responseMimeType: 'application/json' } : {}) },
    }),
    signal: AbortSignal.timeout(60_000),
  })
  const data = (await res.json()) as GeminiResponse
  if (data.error) throw new Error(`Gemini: ${data.error.message}`)
  const text = data.candidates?.[0]?.content?.parts?.map((p) => p.text ?? '').join('') ?? ''
  if (!text) throw new Error(`Gemini: empty answer (${res.status})`)
  return text
}
