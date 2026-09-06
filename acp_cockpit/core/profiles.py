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
    # "owner/repo" on GitHub; the daily watch reads its releases and issues
    upstream_repo: str | None = None
    # [{option_id, mode}]: after answering a permission with option_id,
    # re-assert `mode` (agents that change mode silently on approval)
    permission_mode_followups: list = field(default_factory=list)
    caveats: list = field(default_factory=list)
    extensions: list = field(default_factory=list)
    # Agent-specific session options handed to the agent verbatim (the Claude
    # adapter merges them into its SDK call via `_meta.claudeCode.options`).
    # Passthrough: the engine validates the shape, never the contents.
    client_options: dict = field(default_factory=dict)
    # {config id: [substring, ...]} — the order the AGENT's options should be
    # offered in, when the order it sends is not the useful one. Each entry is
    # matched case-insensitively against an option's value and its name, so a
    # versioned id (`claude-fable-5-1[1m]`) is still matched by `fable`.
    # Options nothing matches keep their order and follow the matched ones.
    config_option_order: dict = field(default_factory=dict)
    # {name: dotted path under `_meta`} — every vendor `_meta` key the engine
    # reads or writes for this agent. Names the engine knows:
    # `session_options` (where `client_options` go on session creation),
    # `prompt_suggestion`, `rate_limit`, `parent_tool_call`, `tool_name`.
    # A name the profile leaves out is a feature this agent does not have.
    meta: dict = field(default_factory=dict)
    # Session-creation choices the launcher offers for this agent:
    # [{id, label, title?, options: [{value, text, client_options}]}]. The
    # chosen option's `client_options` are merged over the profile's.
    launch_choices: list = field(default_factory=list)


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
    upstream_repo = raw.get("upstream_repo")
    if upstream_repo is not None and not isinstance(upstream_repo, str):
        raise ProfileError(f"{path}: 'upstream_repo' must be a string")
    followups = raw.get("permission_mode_followups", [])
    if not isinstance(followups, list) or not all(
            isinstance(f, dict) and isinstance(f.get("option_id"), str)
            and isinstance(f.get("mode"), str) for f in followups):
        raise ProfileError(f"{path}: 'permission_mode_followups' must be a "
                           "list of {option_id, mode} tables")
    client_options = raw.get("client_options", {})
    if not isinstance(client_options, dict):
        raise ProfileError(f"{path}: 'client_options' must be a table")
    order = raw.get("config_option_order", {})
    if not isinstance(order, dict) or not all(
            isinstance(k, str) and isinstance(v, list)
            and all(isinstance(x, str) and x for x in v)
            for k, v in order.items()):
        raise ProfileError(f"{path}: 'config_option_order' must map a config "
                           "id to a list of match strings")
    meta = raw.get("meta", {})
    if not isinstance(meta, dict) or not all(
            isinstance(k, str) and isinstance(v, str) and v
            for k, v in meta.items()):
        raise ProfileError(f"{path}: 'meta' must map names to dotted paths "
                           "under _meta")
    choices = raw.get("launch_choices", [])
    if not isinstance(choices, list) or not all(_launch_choice_ok(c)
                                                for c in choices):
        raise ProfileError(f"{path}: 'launch_choices' must be a list of "
                           "{id, label, options: [{value, text, "
                           "client_options}]} tables")
    if (client_options or any(o.get("client_options")
                              for c in choices for o in c["options"])) \
            and "session_options" not in meta:
        raise ProfileError(f"{path}: client options need 'meta.session_"
                           "options' to say where the agent reads them")
    return AgentProfile(
        id=raw["id"], name=raw["name"], command=list(raw["command"]),
        install_hint=raw["install_hint"], env_scrub=list(raw["env_scrub"]),
        env_set=dict(raw.get("env_set", {})),
        env_resolve=dict(env_resolve),
        npm_package=npm_package,
        upstream_repo=upstream_repo,
        permission_mode_followups=[dict(f) for f in followups],
        caveats=list(raw.get("caveats", [])),
        extensions=list(raw.get("extensions", [])),
        client_options=dict(client_options),
        config_option_order={k: list(v) for k, v in order.items()},
        meta=dict(meta),
        launch_choices=[{**c, "options": [
            {"client_options": {}, **o} for o in c["options"]]}
            for c in choices],
    )


def _launch_choice_ok(c) -> bool:
    if not isinstance(c, dict) or not isinstance(c.get("id"), str) \
            or not isinstance(c.get("label"), str):
        return False
    if "title" in c and not isinstance(c["title"], str):
        return False
    options = c.get("options")
    return isinstance(options, list) and bool(options) and all(
        isinstance(o, dict) and isinstance(o.get("value"), str)
        and isinstance(o.get("text"), str)
        and isinstance(o.get("client_options", {}), dict)
        for o in options)


def load_profiles(*directories) -> dict[str, AgentProfile]:
    """Profiles from each directory in turn; a later directory overrides
    an earlier one by `id`, and a directory that does not exist is simply
    empty. The server reads the profiles shipped inside the package and
    then the user's own `~/.acp-cockpit/agents/`, so an installed copy
    can be given a local adapter build without touching site-packages."""
    out: dict[str, AgentProfile] = {}
    for directory in directories:
        directory = Path(directory)
        if not directory.is_dir():
            continue
        for p in sorted(directory.glob("*.toml")):
            prof = load_profile(p)
            out[prof.id] = prof
    return out
