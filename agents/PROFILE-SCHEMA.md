# Agent profile schema (`agents/*.toml`)

The engine consumes any conforming profile; adding an agent means adding a
file here, never touching `core/`.

## Required fields

| Field | Type | Meaning |
|---|---|---|
| `id` | string | Stable identifier; the file's key in the API (`"claude"`). |
| `name` | string | Display name shown in the launcher (`"Claude Code"`). |
| `command` | list of strings | The ACP agent/adapter argv. `command[0]` is resolved on `PATH` at spawn time (Windows `.cmd` shims included). Example: `["claude-code-acp"]`. |
| `install_hint` | string | Shown when `command[0]` is not found. Example: `"npm install -g @zed-industries/claude-code-acp"`. |
| `env_scrub` | list of strings | Environment variable names or `fnmatch` patterns removed from the child environment. Example: `["CLAUDECODE", "CLAUDE_CODE_*"]`. |

## Optional fields

| Field | Type | Meaning |
|---|---|---|
| `env_set` | table (string → string) | Environment variables added to the child. Default `{}`. |
| `caveats` | array of tables | Known limitations, each `{id, text}`; shown in the launcher and available over `GET /api/profiles`. |
| `extensions` | list of strings | Vendor `_meta` extension names the agent is known to use; surfaced in the record, never interpreted by the engine. Default `[]`. |

## Example

```toml
id = "claude"
name = "Claude Code"
command = ["claude-code-acp"]
install_hint = "npm install -g @zed-industries/claude-code-acp"
env_scrub = ["CLAUDECODE", "CLAUDE_CODE_*"]

[[caveats]]
id = "model-picker"
text = "The interactive /model picker has no ACP equivalent."
```
