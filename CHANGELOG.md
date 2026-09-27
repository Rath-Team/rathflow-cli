# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/Rath-Team/rathflow-cli/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/Rath-Team/rathflow-cli/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/Rath-Team/rathflow-cli/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Rath-Team/rathflow-cli/releases/tag/v0.1.0
