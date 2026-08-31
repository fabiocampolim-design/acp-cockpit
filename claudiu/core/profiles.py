"""Agent profiles: everything agent-specific, loaded from TOML data."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


class ProfileError(Exception):
    pass


@dataclass(frozen=True)
class AgentProfile:
    id: str
    name: str
    command: list[str]
    install_hint: str
    env_scrub: list[str]
    env_set: dict = field(default_factory=dict)
    caveats: list = field(default_factory=list)
    extensions: list = field(default_factory=list)


_REQUIRED = ("id", "name", "command", "install_hint", "env_scrub")


def load_profile(path: Path) -> AgentProfile:
    try:
        raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ProfileError(f"{path}: {exc}") from exc
    for key in _REQUIRED:
        if key not in raw:
            raise ProfileError(f"{path}: missing required field {key!r}")
    if not isinstance(raw["command"], list) or not raw["command"]:
        raise ProfileError(f"{path}: 'command' must be a non-empty list")
    return AgentProfile(
        id=raw["id"], name=raw["name"], command=list(raw["command"]),
        install_hint=raw["install_hint"], env_scrub=list(raw["env_scrub"]),
        env_set=dict(raw.get("env_set", {})),
        caveats=list(raw.get("caveats", [])),
        extensions=list(raw.get("extensions", [])),
    )


def load_profiles(directory: Path) -> dict[str, AgentProfile]:
    out: dict[str, AgentProfile] = {}
    for p in sorted(Path(directory).glob("*.toml")):
        prof = load_profile(p)
        out[prof.id] = prof
    return out
