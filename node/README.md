# rathflow-cli (Node.js)

The **Node.js implementation** of the RathFlow command line client. It has the same
commands, options, output and exit codes as the Python package
([`rathflow-cli` on PyPI](https://pypi.org/project/rathflow-cli/)), so either one works.

- **Zero runtime dependencies** — only Node built-ins (`fetch`, `fs`, `readline`).
- **No build step** — `bin/` and `src/` are the shipped source, runnable as-is.
- **Same config file as the Python CLI** (`~/.config/rathflow/config.json`, mode `0600`),
  so logging in with one implementation works for both.

Requires **Node 20+**.

## Install

```bash
npm install -g rathflow-cli     # installs the `rathflow` command
rathflow --version
```

Without a global install:

```bash
npx rathflow-cli --help
```

The Python CLI uses the same binary name (`rathflow`). Install only one globally, or
call the other by path.

## Quick start

```bash
rathflow auth login -e you@example.com     # prompts for the password, never echoes it
rathflow whoami                            # identity, scope and reachable projects
rathflow project use <project_id>          # pin the default project scope
rathflow session list
```

The built-in gateway default is the hosted `https://rathflow.lynwe.com`. Point it
elsewhere with `--base-url`, `RATHFLOW_BASE_URL`, or `rathflow config set base_url <url>`.

## How it drives the API

- Every request goes through the endpoint table in `src/endpoints.js`; command code never
  contains a URL literal. `npm run selftest` fails the build if the table drifts from the
  upstream generated `endpoints.ts` (point `RATHFLOW_ENDPOINTS_TS` at it), if a command
  hardcodes a URL, or if a multi-segment path param would escape its endpoint
  (`..`/`.` segments are rejected).
- Streaming endpoints (sandbox exec/code/files/logs, session events, memory search/watch,
  agent attachments) are read as newline-delimited JSON frames; the reader rejects unknown
  frame keys instead of guessing.
- Credentials come from `auth.Login` response bodies only — never cookies — so the CLI is
  not subject to the gateway's CSRF gate.

## Configuration

| Item | Value |
| --- | --- |
| Config file | `$RATHFLOW_CONFIG_DIR/config.json`, else `~/.config/rathflow/config.json` |
| Precedence | `--base-url` / `--project` flag > environment > profile > built-in default |
| Environment | `RATHFLOW_BASE_URL`, `RATHFLOW_PROJECT`, `RATHFLOW_TOKEN`, `RATHFLOW_CONFIG_DIR` |
| Profiles | `--profile` / `-p <name>`; `rathflow config list` shows all |

`config show` prints the effective values plus the raw environment variables, so you can
tell whether an env var is actually overriding the saved profile.

## Development

```bash
node bin/rathflow.mjs --help     # run from a checkout
npm test                         # selftest + CLI smoke
```

`npm run selftest` is the gate: endpoint table vs upstream generated routes, no URL
literals in command code, and the multi-segment path guard.

## License

MIT — see [LICENSE](./LICENSE). The Python implementation lives in the repository root.
