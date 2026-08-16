"""Load Agent SKILL.md files from app/skills/."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"
DEFAULT_SKILL_ID = "seedance-tvc"

_FRONT = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


@dataclass(frozen=True)
class Skill:
    id: str
    name: str
    description: str
    body: str
    full: str


def _parse_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    text = raw.replace("\r\n", "\n")
    m = _FRONT.match(text)
    if not m:
        return {}, text.strip()
    meta: dict[str, str] = {}
    key = ""
    buf: list[str] = []
    for line in m.group(1).splitlines():
        if line.startswith("  ") and key:
            buf.append(line.strip())
            continue
        if ":" in line and not line.startswith(" "):
            if key:
                meta[key] = " ".join(buf).strip().strip("\"'")
            key, _, rest = line.partition(":")
            key = key.strip()
            rest = rest.strip()
            if rest == ">|" or rest == ">" or rest == ">|-":
                buf = []
            else:
                buf = [rest.strip("\"'")]
        elif key:
            buf.append(line.strip())
    if key:
        meta[key] = " ".join(buf).strip().strip("\"'")
    return meta, (m.group(2) or "").strip()


def load_skills() -> dict[str, Skill]:
    out: dict[str, Skill] = {}
    if not SKILLS_DIR.is_dir():
        return out
    for d in sorted(SKILLS_DIR.iterdir()):
        path = d / "SKILL.md"
        if not d.is_dir() or not path.is_file():
            continue
        raw = path.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(raw)
        sid = (meta.get("name") or d.name).strip()
        display = (meta.get("title") or meta.get("display_name") or sid).strip()
        desc = (meta.get("description") or "").strip()
        out[sid] = Skill(id=sid, name=display, description=desc, body=body, full=raw)
    return out


def get_skill(skill_id: str) -> Skill | None:
    if not (skill_id or "").strip():
        return None
    return load_skills().get(skill_id.strip())
