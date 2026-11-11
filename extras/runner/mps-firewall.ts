// Extra (extras/README.md), runs only with AOS_EXTRA_MPS_FIREWALL=1.
// Keeps the MeshCentral MPS port (4433 on aos-mesh) open to the home public IP only.
// Intel AMT connects out from home to the MPS, so when the ISP hands out a new IP both gates move:
//  1. the Oracle NSG ingress rule (OCI CLI, API key in ~/.oci, profile from AOS_OCI_PROFILE)
//  2. the VM's own iptables rule (ssh over Tailscale)
import { spawnSync } from 'node:child_process'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const NSG_ID = process.env.OCI_NSG_ID ?? '' // the NSG holding the MPS port rule, in .env.local
const VM = process.env.AOS_VM ?? '' // ubuntu@<VM Tailscale IP>, in .env.local
const MPS_PORT = 4433
const OCI = process.env.OCI_CLI ?? 'oci' // found on PATH
const REGION = process.env.AOS_OCI_REGION ?? 'ap-mumbai-1'

type NsgRule = {
  id: string
  direction: string
  description?: string
  'tcp-options'?: { 'destination-port-range'?: { min: number; max: number } }
}

const run = (cmd: string, args: string[], input?: string): string => {
  const r = spawnSync(cmd, args, { input, encoding: 'utf8', timeout: 60_000 })
  if (r.status !== 0) throw new Error(`${cmd} ${args[0] ?? ''} failed: ${(r.stderr || r.stdout || '').trim().slice(0, 300)}`)
  return r.stdout
}

const oci = (args: string[]): string =>
  run(OCI, [...args, '--profile', process.env.AOS_OCI_PROFILE ?? 'AOS', '--region', REGION])

const updateNsg = (ip: string): void => {
  const rules = (JSON.parse(oci(['network', 'nsg', 'rules', 'list', '--nsg-id', NSG_ID, '--all'])) as { data: NsgRule[] }).data
  const rule = rules.find(
    (r) => r.direction === 'INGRESS' && r['tcp-options']?.['destination-port-range']?.min === MPS_PORT,
  )
  if (!rule) throw new Error(`no ingress rule for port ${MPS_PORT} in the NSG`)
  const updated = [
    {
      id: rule.id,
      direction: 'INGRESS',
      protocol: '6',
      source: `${ip}/32`,
      sourceType: 'CIDR_BLOCK',
      isStateless: false,
      description: 'Intel AMT CIRA to MeshCentral MPS, home IP only (kept current by aos runner)',
      tcpOptions: { destinationPortRange: { min: MPS_PORT, max: MPS_PORT } },
    },
  ]
  oci(['network', 'nsg', 'rules', 'update', '--nsg-id', NSG_ID, '--security-rules', JSON.stringify(updated)])
}

const updateVmFirewall = (ip: string): void => {
  // Replace whatever source the 4433 rule had with the new home IP, then persist.
  const script = [
    'set -e',
    `while sudo iptables -S INPUT | grep -q -- "--dport ${MPS_PORT}"; do`,
    `  rule=$(sudo iptables -S INPUT | grep -- "--dport ${MPS_PORT}" | head -1 | sed 's/^-A /-D /')`,
    '  eval sudo iptables $rule',
    'done',
    `sudo iptables -I INPUT 5 -p tcp -s ${ip}/32 --dport ${MPS_PORT} -m state --state NEW -j ACCEPT`,
    'sudo netfilter-persistent save >/dev/null 2>&1',
  ].join('\n')
  run('ssh', ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', VM, 'bash -s'], script)
}

export const allowHomeIp = (ip: string): void => {
  if (!/^\d{1,3}(\.\d{1,3}){3}$/.test(ip)) throw new Error(`not an IPv4 address: ${ip}`)
  if (!VM || !NSG_ID) throw new Error('set AOS_VM and OCI_NSG_ID in .env.local')
  updateNsg(ip)
  updateVmFirewall(ip)
}

// State stays in runner/ (gitignored), where it lived before the move to extras/.
const LAST_IP = join(import.meta.dir, '..', '..', 'runner', '.home-ip')
const FAILED_IP = join(import.meta.dir, '..', '..', 'runner', '.home-ip-failed')

/** If the home public IP changed, moves the MPS firewall to it. AOS_HOME_IP is the IP the rule started with. */
export const checkHomeIp = async (notify: (text: string) => Promise<boolean>): Promise<void> => {
  const initial = process.env.AOS_HOME_IP
  if (!initial) return
  const res = await fetch('https://api.ipify.org', { signal: AbortSignal.timeout(8000) }).catch(() => null)
  const ip = res?.ok ? (await res.text()).trim() : ''
  if (!/^\d{1,3}(\.\d{1,3}){3}$/.test(ip)) return
  const allowed = existsSync(LAST_IP) ? readFileSync(LAST_IP, 'utf8').trim() : initial
  if (ip === allowed) return
  try {
    allowHomeIp(ip)
    writeFileSync(LAST_IP, ip)
    await notify(`🔁 Home IP changed ${allowed} → ${ip}. MPS firewall (Oracle NSG + aos-mesh iptables) updated, AMT reconnects within minutes.`)
  } catch (e) {
    const failed = existsSync(FAILED_IP) ? readFileSync(FAILED_IP, 'utf8').trim() : ''
    if (failed === ip) return // already reported this IP
    writeFileSync(FAILED_IP, ip)
    await notify(
      `⚠️ Home IP changed ${allowed} → ${ip} but the MPS firewall update failed: ${e instanceof Error ? e.message : 'unknown'}\n` +
        `AMT power-on from outside is down until the 4433 rule allows ${ip}/32 (the Oracle NSG + aos-mesh iptables).`,
    )
  }
}
