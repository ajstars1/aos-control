"""Settings the desk tools share with the rest of aos, from the environment or the repo's .env.local.

Only these keys are read: AOS_OWNER_NAME (who the desktop belongs to), AOS_WORKDIR (where a bare folder name like
"myproject" is looked up; default the home folder) and AOS_DM_CHANNEL (the owner's Discord DM channel id; default the
id systemd/discord-agent.sh saves in ~/.cache/aos/discord-dm-channel).
"""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOME = Path.home()


def conf(key: str, default: str = "") -> str:
    value = os.environ.get(key, "")
    if value:
        return value
    try:
        for line in (REPO / ".env.local").read_text().splitlines():
            if line.startswith(key + "="):
                value = line.split("=", 1)[1].strip().strip("'\"")
    except OSError:
        pass
    return value or default


def workdir() -> Path:
    return Path(os.path.expanduser(conf("AOS_WORKDIR") or "~"))


def owner() -> str:
    return conf("AOS_OWNER_NAME") or "the user"


def dm_channel() -> str:
    """The owner's Discord DM channel id, or "" when the Discord agent has not looked it up yet."""
    value = conf("AOS_DM_CHANNEL")
    if value:
        return value
    try:
        return (HOME / ".cache" / "aos" / "discord-dm-channel").read_text().strip()
    except OSError:
        return ""
