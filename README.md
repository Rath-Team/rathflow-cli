# rathflow-cli

[![PyPI](https://img.shields.io/pypi/v/rathflow-cli.svg)](https://pypi.org/project/rathflow-cli/)
[![Python](https://img.shields.io/pypi/pyversions/rathflow-cli.svg)](https://pypi.org/project/rathflow-cli/)
[![npm](https://img.shields.io/npm/v/rathflow-cli.svg)](https://www.npmjs.com/package/rathflow-cli)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

The RathFlow command line client. It talks to the RathFlow northbound REST API and
covers sessions, memory, sandboxes, agents, assets, projects, billing and
workflows. Two implementations ship from this repository — **Python** (`rathflow_cli/`)
and **Node.js** ([`node/`](node/README.md)) — with the same commands, options, output and
exit codes. They share one config file, so you can switch between them freely.

## Install

Python (3.10+):

```bash
uv tool install rathflow-cli
# or
pipx install rathflow-cli
# or
pip install rathflow-cli
```

Node.js (20+):

```bash
npm install -g rathflow-cli
```

Both install a `rathflow` command; install only one globally, or call the other by path.
The two packages are released together from the same `v*` tag.

## Quick start

```bash
# Log in with your email and password (the password prompt does not echo).
rathflow auth login -e you@example.com

# Who am I, what can I reach.
rathflow whoami

# Pick a project scope; every later command carries it.
rathflow project list
rathflow project use <project_id>

# Read something.
rathflow session list
```

The default gateway is `https://rathflow.lynwe.com`. Point it elsewhere with
`--base-url`, `RATHFLOW_BASE_URL`, or `rathflow config set base_url <url>`.

## Commands

| Group | What it covers |
| --- | --- |
| `auth` | log in / out, register, profile (`profile`, `profile-update`, `change-password`, `set-email`, `set-avatar`), API keys |
| `config` | local profiles (`list`, `show`, `set`, `use`) |
| `org` | organizations (`list`, `create`, `invite`, `accept`) |
| `project` | projects, scope switching, project config, share links |
| `session` | sessions, blocks, events |
| `memory` | memory entries, search, commit tasks |
| `sandbox` | sandboxes, exec, code, files, logs |
| `agent` | agent definitions, versions, prompts, runs, attachments |
| `asset` | assets, versions, credentials, publish |
| `billing` | subscription, usage, invoices |
| `workflow` | workflows (`list`, `get`, `create`, `delete`, `counts`) |
| `admin` | platform administration (platform admins only) |

Two more entry points sit at the root:

- `rathflow whoami` — identity, scope and reachable projects.
- `rathflow api <Key>` — call any endpoint directly; `rathflow api --list` prints
  the whole table. Streaming endpoints stream.

Every group has `--help`, e.g. `rathflow session --help`.

## Authentication

`rathflow auth login` exchanges your email and password for a JWT, stored in the
CLI config file (mode `0600`). The CLI sends it as a `Bearer` token and never
touches cookies, so it is unaffected by the browser CSRF rules.

For unattended use, issue a long-lived API key and pass it through the
environment:

```bash
rathflow auth key-create          # prints the key once, right here
export RATHFLOW_TOKEN=rf_...      # or: rathflow config set token rf_...
```

## Configuration

Precedence, highest first: command-line flag > environment variable > active
profile > built-in default. Profiles live in
`~/.config/rathflow/config.json` (override the directory with
`RATHFLOW_CONFIG_DIR`).

| Variable | Meaning |
| --- | --- |
| `RATHFLOW_BASE_URL` | Gateway address |
| `RATHFLOW_PROJECT` | Project scope |
| `RATHFLOW_TOKEN` | Bearer token / API key |
| `RATHFLOW_CONFIG_DIR` | Config directory |

## Output

- Default: human-readable tables.
- `--json`: one stable JSON document, for scripts.
- `--quiet` / `-q`: primary keys only.

Exit codes are stable: `0` success, and non-zero for usage errors, API errors and
remote command failures (a sandbox `exec` returns the remote exit code).

## Proxies

The CLI respects the standard proxy variables. One caveat: `httpx` cannot use a
SOCKS proxy unless `socksio` is installed. If your environment sets
`ALL_PROXY=socks://...` (some Clash setups do), install the extra or the CLI
fails to start with `Unknown scheme for proxy URL`:

```bash
uv tool install 'rathflow-cli[socks]'
# or clear it for this command only
ALL_PROXY= rathflow whoami
```

## Development

```bash
uv venv --python 3.12 .venv
uv pip install -e .
.venv/bin/rathflow --help
.venv/bin/python -m rathflow_cli.selftest
```

`selftest` checks that no command hard-codes a URL and, when the upstream
generated endpoint table is available (`RATHFLOW_ENDPOINTS_TS`), that
`rathflow_cli/endpoints.py` still matches it.

## License

MIT — see [LICENSE](LICENSE).
