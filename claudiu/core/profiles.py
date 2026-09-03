# SPDX-License-Identifier: Apache-2.0
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
    env_resolve: dict = field(default_factory=dict)  # VAR -> command name
    npm_package: str | None = None   # for the installed-vs-latest drift check
    # [{option_id, mode}]: after answering a permission with option_id,
    # re-assert `mode` (agents that change mode silently on approval)
    permission_mode_followups: list = field(default_factory=list)
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
    env_resolve = raw.get("env_resolve", {})
    if not isinstance(env_resolve, dict) or not all(
            isinstance(k, str) and isinstance(v, str) and v
            for k, v in env_resolve.items()):
        raise ProfileError(f"{path}: 'env_resolve' must map variable names "
                           "to command names")
    npm_package = raw.get("npm_package")
    if npm_package is not None and not isinstance(npm_package, str):
        raise ProfileError(f"{path}: 'npm_package' must be a string")
    followups = raw.get("permission_mode_followups", [])
    if not isinstance(followups, list) or not all(
            isinstance(f, dict) and isinstance(f.get("option_id"), str)
            and isinstance(f.get("mode"), str) for f in followups):
        raise ProfileError(f"{path}: 'permission_mode_followups' must be a "
                           "list of {option_id, mode} tables")
    return AgentProfile(
        id=raw["id"], name=raw["name"], command=list(raw["command"]),
        install_hint=raw["install_hint"], env_scrub=list(raw["env_scrub"]),
        env_set=dict(raw.get("env_set", {})),
        env_resolve=dict(env_resolve),
        npm_package=npm_package,
        permission_mode_followups=[dict(f) for f in followups],
        caveats=list(raw.get("caveats", [])),
        extensions=list(raw.get("extensions", [])),
    )


def load_profiles(directory: Path) -> dict[str, AgentProfile]:
    out: dict[str, AgentProfile] = {}
    for p in sorted(Path(directory).glob("*.toml")):
        prof = load_profile(p)
        out[prof.id] = prof
    return out
