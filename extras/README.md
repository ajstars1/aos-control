# Extras: optional add-ons for one specific hardware setup

Everything in this folder was built for the maintainer's own machine: a Dell OptiPlex with Intel AMT, an Oracle Cloud free VM running MeshCentral, Hyprland with greetd, and a small business that runs a WhatsApp booking bot. **You do not need any of it.** The runner never loads this code unless you switch it on, and every switch defaults to off.

They are published because they show how far the setup can go, and because parts may be useful to you. Expect to adapt them.

| Extra | Switch (.env.local) | What it does |
|---|---|---|
| MPS firewall (`runner/mps-firewall.ts`) | `AOS_EXTRA_MPS_FIREWALL=1`, plus `AOS_HOME_IP`, `AOS_VM`, `OCI_NSG_ID` | When your home public IP changes, moves the MeshCentral MPS port (4433) rule in the Oracle NSG and the VM's iptables to the new IP, so Intel AMT can still reach it. Needs the OCI CLI (profile `AOS_OCI_PROFILE`, default `AOS`; region `AOS_OCI_REGION`). |
| MeshCentral backup (`runner/mesh-backup.ts`) | `AOS_EXTRA_MESH_BACKUP=1`, plus `AOS_VM` | Once a day copies the newest MeshCentral auto-backup from the VM to `~/Backups/aos-mesh` over SSH (keeps 7, owner-only). |
| Business watchers (`runner/watchers.ts`) | `AOS_EXTRA_WATCHERS=1`, plus `AOS_WATCHERS_DIR`, `AOS_WATCHERS_LABEL` | Every 30 minutes runs `scripts/watch.py <since>` in `AOS_WATCHERS_DIR` (a read-only Firestore query) and pings Discord about new bookings, leads, failed WhatsApp sends and chats waiting for a person. |
| Oracle ARM VM hunter (`runner/ai-vm.ts`, `oci/aos-ai-init.sh`) | not wired into the runner | Keeps trying to launch a free Oracle A1 VM and sends its Tailscale login link. Needs `OCI_SUBNET_ID`, `OCI_IMAGE_ID`, `OCI_AD`. |
| Boot auto-login (`boot/apply.sh`, `boot/autologin-session.sh`, `boot/lock-on-autologin.sh`) | run by hand with sudo | greetd logs you in once at boot and Hyprland locks the screen at once, so the bot, VNC and runner come back after a reboot or power cut while the desk stays locked. Undo with `--undo`. |
| TOTP unlock (`boot/unlock/`) | `AOS_EXTRA_UNLOCK=1` after `sudo bash extras/boot/unlock/install.sh` | A root service that unlocks hyprlock when you send `unlock 123456` (a code from your authenticator app) to the Discord agent. The secret never leaves root. |
| Intel AMT + MeshCentral (`boot/BIOS-AMT-CHECKLIST.md`) | manual | BIOS and MEBx steps for remote power on/off and a KVM that works in the BIOS. |
| aos-cloud bot (`cloud/`) | `AOS_EXTRA_CLOUD=1` once deployed | A second, always-on Discord bot on the VM: PC power through MeshCentral, task commands through the aos MCP, Gemini answers, voice notes. Deploy with `bash extras/cloud/deploy.sh` and `bash extras/cloud/set-secrets.sh` (needs `AOS_VM`, `MESH_URL`, `MESH_NODE_ID`). |

The switches accept `1`, `true`, `yes` or `on`. Anything else, or nothing, is off.

State files stay in `runner/` (gitignored), next to the core runner's.
