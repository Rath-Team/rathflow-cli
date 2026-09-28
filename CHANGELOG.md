# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.4] - 2026-09-28

### Added

- `rathflow mcp serve` — an MCP (Model Context Protocol) server on stdio, so MCP
  clients like Codex or Claude can drive RathFlow without shell access. It ships
  a curated task-shaped tool set instead of a 1:1 mapping of the 111 endpoints:
  14 read tools by default, plus 5 write tools that only appear when
  `RATHFLOW_MCP_WRITE=1` is set. Endpoints without a named tool stay reachable
  through `rathflow_endpoints` + `rathflow_api_call`, the same escape hatch as
  `rathflow api <Key>`.
- The server advertises protocol `2025-11-25` and negotiates down to the client's
  version. Auth reuses the CLI config and the token is refreshed mid-session, so a
  long-lived MCP session survives expiry. When there are no credentials it tells
  the user to run `rathflow auth login` — it never suggests cloning sources or
  running a local Gateway.
- Three new selftest checks cover the MCP server: version negotiation, tool schema
  validity, protocol error codes, and the "no credentials" wording.

### Fixed

- A 401 replay sent the **previous** `Authorization` header. `Client._send` built
  the headers once before the retry loop, so after `refresh()` rotated the access
  token the replay kept the stale one and 401'd again. Long-lived processes (the
  MCP server, or any session that outlives its token) could not recover without a
  restart. Headers are now rebuilt per attempt.

### Notes

- `rathflow mcp serve` currently ships in the **Python** package only; the Node
  CLI has not been ported yet.

## [0.1.3] - 2026-09-27

### Fixed

- Multi-segment path params (`memory read/write/delete`, `sandbox cat`) now reject
  empty, `.` and `..` segments. Such a value was passed through unencoded (`.` is
  unreserved, so percent-encoding does not touch it) and the HTTP client then
  normalized it away: `memory read memories/../../secrets` actually requested
  `/api/v1/secrets`. That silently hit a different endpoint and bypassed the
  command's own "first segment must be `memories`/`resources`" guard.
- `python -m rathflow_cli.selftest` now checks that guard, so CI catches any
  regression without a network call.
- Global flags placed **after** a subcommand are hoisted again for every command.
  `_value_opts()` treated positional argument names as value-taking options, so
  `rathflow auth profile --json` (and anything else whose last word matched an
  argument name, e.g. `config use <profile>`) failed with "No such option".

### Added

- The 8 REST endpoints that upstream `endpoints.ts` (111 total) had but this
  package was missing, each with a command:
  `auth profile`, `auth profile-update`, `auth change-password`, `auth set-email`,
  `auth set-avatar`, `org create`, `workflow counts`, `agent attachment`.
- `agent.ReadAttachment` is marked streaming (it returns `AttachmentChunk`
  frames), so `agent attachment` writes bytes chunk by chunk instead of buffering.

## [0.1.2] - 2026-09-27

### Fixed

- `rathflow config show` flattens the `env` block in human-readable output; nested
  dicts were truncated to ~48 columns, so only `RATHFLOW_BASE_URL` was visible.
  `--json` keeps the nested `env` object.

## [0.1.1] - 2026-09-27

### Fixed

- `rathflow config show` no longer reports the merged effective `base_url`/`project`
  as if they were environment variables. The `env` block now shows the real
  `RATHFLOW_BASE_URL` / `RATHFLOW_PROJECT` / `RATHFLOW_TOKEN` values, with
  `(未设置)` when unset, so you can tell whether an env var is actually overriding.

### Added

- `rathflow --version`.

## [0.1.0] - 2026-09-27

### Added

- First public release of the RathFlow CLI.
- Email/password login (`rathflow auth login`), token refresh and profile config.
- Command groups covering the RathFlow northbound REST API: `auth`, `config`,
  `org`, `project`, `session`, `memory`, `sandbox`, `agent`, `asset`,
  `billing`, `workflow`, `admin`, plus the `api` escape hatch.
- `--json` / `--quiet` output modes and the `rathflow_cli.selftest` endpoint check.

[Unreleased]: https://github.com/Rath-Team/rathflow-cli/compare/v0.1.3...HEAD
[0.1.3]: https://github.com/Rath-Team/rathflow-cli/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/Rath-Team/rathflow-cli/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/Rath-Team/rathflow-cli/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Rath-Team/rathflow-cli/releases/tag/v0.1.0
