# Releasing

Both implementations live in this repository and ship from **one tag**, with the **same
version number**.

## 1. Bump the versions (keep them in sync)

- `pyproject.toml` → `[project] version`
- `rathflow_cli/__init__.py` → `__version__`
- `node/package.json` → `version`
- `CHANGELOG.md` → new section

## 2. Tag and push

```bash
git tag -a v0.1.4 -m "v0.1.4"
git push origin v0.1.4
```

`.github/workflows/release.yml` then:

| Job | What it does |
| --- | --- |
| `build` | builds the sdist/wheel, installs the wheel in a clean venv, runs `python -m rathflow_cli.selftest` |
| `pypi` | publishes to PyPI through **Trusted Publishing** (OIDC, environment `pypi`) |
| `npm` | publishes `node/` to npm; skips when that exact version is already on the registry |
| `github-release` | attaches the built artifacts to the GitHub release |

CI (`.github/workflows/ci.yml`) tests the Python package on 3.10/3.12 and the Node CLI on
Node 20/22/24, including installing the packed tarball into a clean prefix.

## npm credentials

The `npm` job needs one of these, otherwise it logs a warning and skips:

- **`NPM_TOKEN` repository secret** — a granular access token with read/write for
  `rathflow-cli` (npmjs.com → Access Tokens; then GitHub → Settings → Secrets and
  variables → Actions → New repository secret).
- **npm Trusted Publishing (no secret)** — npmjs.com → `rathflow-cli` → Settings →
  Trusted Publisher → GitHub Actions, repository `Rath-Team/rathflow-cli`, workflow
  `release.yml`. The workflow already sets `id-token: write` and passes `--provenance`.

Trusted publishing can only be configured once the package exists, so the **first** npm
release is published locally:

```bash
cd node && npm publish --access public
```

## Verifying a release

```bash
uv tool install rathflow-cli --refresh     # PyPI
npm install -g rathflow-cli@latest         # npm
rathflow --version
```

Package pages: <https://pypi.org/project/rathflow-cli/> ·
<https://www.npmjs.com/package/rathflow-cli>
