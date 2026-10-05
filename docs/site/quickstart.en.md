# Quickstart: validate before deploying

## Portable local starting point (unreleased)

After installing a wheel containing this feature, run `chatglance runtime paths`, then `chatglance runtime init`; review its loopback home page and empty inventories/snapshots. Install a deliberately selected maintained Go-fork binary with `chatglance runtime install-binary --archive reviewed.tar.gz --sha256 EXPECTED_64_HEX --binary-version chatarch-vX.Y.Z+40_LOWERCASE_HEX` (replace the version with the exact observed output), then render review-only units with `chatglance runtime render-portable --output-dir ./review-units`. `runtime serve` is an explicit operator action. The five separate layers are source, wheel, fork binary, runtime configuration/data and OS entry points. The maintained fork owns optional login; generic upstream binaries do not. See the complete [portable deployment guide](deployment.en.md).

Initialization makes no external calls, starts no service, and never redeems account cards; loopback is the default. For opt-in login, provision typed ChatEnv `CHATGLANCE_LOGIN_USER`, `CHATGLANCE_LOGIN_SECRET` and bcrypt `CHATGLANCE_LOGIN_PASSWORD_HASH` before `runtime init --with-auth`. YAML contains only Go `${ENV}` references, resolved from process environment first, then active ChatEnv for the child. `CHATGLANCE_WEB_PORT`, optional `CHATGLANCE_PUBLIC_ORIGIN` / `CHATGLANCE_CONTROL_PORT`, project owner, and refresh cadence/pages are non-secret settings. Keep CRS and GitHub on their shared profile/resolver rather than a new token store; migrate existing sites without exporting secret files. Explicit `render-portable --page projects` creates non-account schedules, while `--controls` additionally needs configured login and a reviewed HTTPS origin. The proxy example preserves same-origin login and redirects old project paths. Nothing publishes or deploys automatically.

Glance's `glance.yml`, widgets, and HTML/CSS define the site. ChatGlance helps generate pages, validate config, and maintain snapshots. Do not treat these examples as a production deployment script.

## 1. Install in an isolated environment and inspect the CLI

Use `python -m pip install -e .` from a source checkout, or `python -m pip install ChatGlance` after checking the version actually published to PyPI. **The optional-login CLI requires 0.1.18 source or a released artifact containing it**; it is not part of published 0.1.17.

```bash
chatglance --version
chatglance --tree-brief
chatglance access render-single-origin-optional-login --help
```

If you need to create a config, consult the [maintained Glance fork](https://github.com/ChatArch/glance) for supported YAML. Prepare **synthetic** `private.yml` and `inventory.json`. Retain existing auth and server routing in the input; never commit real configuration. Unmodified v0.8.5 cannot validate the optional-login config.

## 2. Generate a single-origin candidate

Use an existing non-symlink private directory. Filenames below are placeholders; this command does not touch a running service:

```bash
chatglance access render-single-origin-optional-login \
  --config private.yml \
  --inventory inventory.json \
  --output candidate.yml
```

Only completion status is printed, never `auth` or private rows. The output must differ from its inputs and is atomically written at `0600`. The original home and all other login-required pages retain their identities. The project title stays “项目”, but its canonical slug is `/projects` (deploy an exact proxy redirect for `/项目`). Making home public does not make other pages public.

## 3. Validate, review, then let operators decide on deployment

Use a deliberately selected Glance executable **with** `public` + `authenticated-columns` support:

```bash
glance -config candidate.yml config:validate
```

Check that guest columns contain only literal `private: false` repositories, while signed-in columns contain all rows with Public/Private/Unknown labels. Operators must separately verify sessions, direct private APIs, logout caches, and desktop/mobile navigation in an isolated environment. A candidate alone is not proof of deployment. See [Projects and access](projects.md) and [Refresh and operations](operations.md).
