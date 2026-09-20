<div align="center">
    <a href="https://pypi.python.org/pypi/ChatGlance">
        <img src="https://img.shields.io/pypi/v/ChatGlance.svg" alt="PyPI version" />
    </a>
    <a href="https://github.com/ChatArch/ChatGlance/actions/workflows/ci.yml">
        <img src="https://github.com/ChatArch/ChatGlance/actions/workflows/ci.yml/badge.svg" alt="Tests" />
    </a>
</div>

<div align="center">

[English](README.en.md) | [简体中文](README.md)
</div>

# ChatGlance

`ChatGlance` is the ChatArch/WZHECNU repository for Glance website deployment source and operations helpers. It preserves the current site's page-generation logic, configuration transformations, user-level service templates, verification notes, and safety boundaries; the `chatglance` CLI is only the helper entrypoint for applying those rules.

It is not an npm project and does not reimplement the Glance backend. Upstream Glance remains a Go single-binary dashboard server; `ChatGlance` owns reusable Python code and private deployment records for repository inventory rendering, Glance YAML page generation, inline HTML table generation, selected Disk mountpoint display, and user-level runtime maintenance.

## Reset decisions and manual controls

Subscription cards collapse reset information by default. Forecast details live only in the centered, host-themed popup. Each account has one independent automatic-reset switch, included in the execution checklist and paused/waiting/ready summary. Enabling requires explicit confirmation; there is no immediate-redemption button. See [reset controls](docs/reset-controls.md) for deployment and security boundaries.

## CRS-managed subscriptions (unreleased)

An explicit CRS profile containing a dedicated management Key and fixed account-ID mapping can route subscription collection entirely through the CRS service, keeping upstream OAuth server-owned. This candidate mode requires the corresponding native CRS API and managed ChatCRS client; missing configuration, capabilities or authorization never fall back to local OAuth. Existing mode is not switched automatically, and manual refresh remains non-consuming. See [Codex reset policy](docs/codex-reset-policy.md) for configuration and migration boundaries.

## Repository contents

- `src/chatglance/`: helper code for project, server, and website-service card page generation, Glance YAML patching, runtime maintenance, and user-level systemd unit rendering/installation.
- `tests/`: regression tests for project pages, Disk mountpoint visibility, runtime/systemd helpers, and release workflow contracts.
- `docs/quickstart.md`: new-machine quick start that keeps Glance frontend config primary and `chatglance` as a management helper.
- `docs/cli-tree.md`: full and brief CLI trees generated from the real Click registry, with tested side-effect boundaries.
- `docs/site-architecture.md`: boundary between ChatGlance as a Python package, the Glance runtime, generated config, and runtime data refresh scripts.
- `docs/projects.md`: project-page display contract, PyPI-only version rule, entrypoint-only display rule, actual CLI-tree classification evidence, and refresh review checklist.
- `docs/infra.md`: configuration mechanism, external data-generation chain, refresh workflow, and cron/timer template for the Infra/`服务器` page.
- `docs/deployment/current-site.md`: native CLI and user service/timer deployment contract; concrete topology, secrets and live evidence remain outside the repository.
- `examples/server-inventory.example.yml` / `examples/site-services.example.yml`: sanitized inventory config templates. Real inventories belong in the runtime config directory.
- `chatglance refresh [PAGES]...`: installed-package collection, validation and publication without a source checkout or host-local business scripts.
- `chatglance refresh --scheduled`: explicit scheduled execution for the existing timer, preserving per-account policies and the shared lock.
- `README.md` / `README.en.md` / `CHANGELOG.md`: collaboration and package-facing entry points; do not include live auth, tokens, password hashes, proxy credentials, or secret-bearing files.

## Current capabilities

- Refresh repository inventory JSON from current ChatGH/GitHub data and render a Glance `项目` page with a visible `generated_at` refresh timestamp; version display is PyPI-only, the compact table shows package entrypoints only, and Python early/non-early classification is corrected from latest-PyPI actual CLI tree/help evidence while stale baseline categories remain audit evidence only.
- Generate native-click `详情` buttons in the `项目` table; the detail card shows project description, basics, CLI entrypoints, a brief CLI tree code block with preserved `# ...` comments, and registered ChatEnv Env keys, descriptions, sensitivity flags, and default-presence flags. Projects with ENV metadata expose a CLI/ENV click switch, and no values are shown.
- Keep the current tabs limited to `最近提交`, `PR-issue`, `分类`, and `一览表`.
- Filter the triage tab to repositories with non-zero PR or Issue counts and sort by `(PR, Issue, recent commit)` descending.
- Replace generated legacy pages: `Projects`, `ChatArch Projects`, and `ChatArch Projects List`.
- Patch Glance `server-stats` to show only selected meaningful disks. The current live policy keeps `/` and adds `/home` only when it is a separate mountpoint; each visible entry is written with `hide: false` so the Disk card does not render `n/a`, while snap/loop/tmp overlays stay hidden.
- Select SSH aliases from an Infra inventory YAML, collect a read-only static `server-status.json`, and render the Glance `服务器`/Infra page from that snapshot.
- Keep collapsed server cards limited to IP/CPU/memory/disk/status while GPU, mountpoints, filtered `lsblk`, safe `getdevices` summaries, and `Last Reboot` stay in expandable details.
- Generate a reviewed `网站服务` page from `site-services.yml`: one cover image, description, health status, Uptime detail link, and public jump button per service. Local hosts are used only for probing/operator config and are not shown on the human-facing page.
- Maintain a durable runtime with `runtime maintain`: atomic live-config update, backup, and validation; service lifecycle actions stay outside the default docs examples.
- Render and install user-level systemd units: the main service still starts the upstream Glance Go binary directly; maintenance is an independent oneshot/timer, not a Python server wrapper.
- Install, enable, start, and read back the current Glance page user service/timer from the CLI.

## Quick start

For a new machine that should host a similar but still highly customizable Glance site, start with [`docs/quickstart.md`](docs/quickstart.md): `glance.yml` / widgets / HTML/CSS remain the primary frontend configuration surface, while `chatglance` only manages collection, rendering, validation, backup, and replacement.

```bash
pip install -e ".[dev]"
chatglance --help
chatglance --version
chatglance --tree
chatglance --tree-brief
python -m pytest -q
python -m build
python -m twine check dist/*
```

## Manual refresh and CLI tree

The installed package can refresh an existing runtime without a source checkout:

```bash
python -m pip install ChatGlance==0.1.10
chatglance refresh
chatglance refresh account-limits
chatglance refresh projects sites
```

With no page arguments, refresh only generated pages already configured in Glance. Supported keys are `projects`, `servers`, `sites`, and `account-limits`. The default runtime is `glance/` under the effective ChatArch home; override it with `--runtime-home`.

The command reuses reviewed inventories, existing ChatEnv/snapshot account profiles, and existing GitHub credentials. Manual refresh never redeems reset cards or changes their configured policy. It shares the scheduled-refresh lock, validates candidates before publication, preserves page order and unrelated content, backs up changes, and restarts the existing Glance user service at most once.

Failed pages keep their old artifacts while successful pages continue. Partial/cached results exit nonzero. Use `--no-restart` for external lifecycle ownership, `--json-output` for automation, or `--allow-offline-regression` to intentionally publish newly offline servers. Project refresh reuses CLI evidence only for the same released version, package identity, and entrypoints; `--actual-cli-tree` explicitly re-probes published packages.

Both manual and scheduled refreshes call the installed CLI directly. Retire host-local and checkout-based business-script entrypoints after migration; keep only ChatEnv/secrets, inventories, data and thin service-manager configuration outside the package. Manual refresh neither changes automatic-reset policies nor consumes cards. Required OAuth renewal belongs to ChatCRS 0.3.4 and the standard ChatEnv token lifecycle.

```bash
chatglance refresh --scheduled --runtime-home "$HOME/.chatarch/glance" --json-output
```

Account requests use the profile's reverse-proxy Base URLs, and ChatCRS ignores local proxies. Do not prepend `proxy_on`. Select non-secret inputs explicitly with `--server-inventory`, `--sites-inventory`, `--gatus-db` and the other collector options. Omit `--scheduled` for non-consuming diagnostics.

Read the live command surface with `chatglance --tree` / `--tree-brief`; see [CLI tree](docs/cli-tree.md) and [manual refresh](docs/refresh.md) for configuration and side-effect details.

## CLI examples

Refresh current GitHub/ChatGH project data:

```bash
chatglance projects collect \
  --owner ChatArch \
  --output ~/.chatarch/glance/data/chatarch-projects.json
```

Render only the project page YAML:

```bash
chatglance projects render-page \
  --data /path/to/chatarch-projects.json \
  --output playground/projects-page.yml
```

Write an updated Glance config copy:

```bash
chatglance projects update-config \
  --data /path/to/chatarch-projects.json \
  --config /path/to/glance.yml \
  --output playground/glance.with-projects.yml
```

Patch Disk display to root-only and write a config copy:

```bash
chatglance disks root-only \
  --config /path/to/glance.yml \
  --output playground/glance.root-disk.yml
```

Inspect the aliases selected by the Infra config:

```bash
chatglance servers candidates \
  --inventory-config ~/.chatarch/glance/config/server-inventory.yml
```

Manually refresh Infra static data and page YAML:

```bash
chatglance servers collect \
  --inventory-config ~/.chatarch/glance/config/server-inventory.yml \
  --output ~/.chatarch/glance/data/server-status.json

chatglance servers render-page \
  --inventory-config ~/.chatarch/glance/config/server-inventory.yml \
  --data ~/.chatarch/glance/data/server-status.json \
  --output ~/.chatarch/glance/data/server-page.yml

chatglance servers update-config \
  --inventory-config ~/.chatarch/glance/config/server-inventory.yml \
  --data ~/.chatarch/glance/data/server-status.json \
  --config ~/.chatarch/glance/config/glance.yml \
  --output ~/.chatarch/glance/config/glance.yml.infra-candidate
```

Generate website-service data, covers, and page YAML:

```bash
chatglance sites collect \
  --inventory-config ~/.chatarch/glance/config/site-services.yml \
  --gatus-db ~/.chatarch/uptime-gatus/data/gatus.db \
  --output ~/.chatarch/glance/data/site-services.json

chatglance sites export-covers \
  --data ~/.chatarch/glance/data/site-services.json \
  --output-dir playground/site-covers \
  --public-base-url https://share.public.wzhecnu.cn/chatglance-site-covers/ \
  --updated-data ~/.chatarch/glance/data/site-services.json

chatglance sites render-page \
  --data ~/.chatarch/glance/data/site-services.json \
  --output ~/.chatarch/glance/data/site-services-page.yml

chatglance sites update-config \
  --data ~/.chatarch/glance/data/site-services.json \
  --config ~/.chatarch/glance/config/glance.yml \
  --output ~/.chatarch/glance/config/glance.yml.sites-candidate
```

Maintain a durable Glance runtime (default `~/.chatarch/glance`):

```bash
chatglance runtime maintain \
  --runtime-home ~/.chatarch/glance
```

Render recommended systemd user units:

```bash
chatglance runtime render-systemd \
  --runtime-home ~/.chatarch/glance \
  --chatglance-bin ~/.chatarch/venv/bin/chatglance \
  --output-dir playground/systemd
```

Install and enable user-level systemd units (writes `~/.config/systemd/user`, no sudo):

```bash
chatglance runtime install-systemd \
  --runtime-home ~/.chatarch/glance \
  --chatglance-bin ~/.chatarch/venv/bin/chatglance \
  --start
```

Start/read back the current page user service/timer:

```bash
chatglance runtime start
chatglance runtime status
```

## Runtime boundary

Recommended topology: **systemd runs Glance directly; chatglance performs maintenance only**.

- Main service: `chatarch-glance.service` executes `~/.chatarch/glance/bin/glance -config ~/.chatarch/glance/config/glance.yml` directly.
- Reusable source, scripts, and docs live inside the ChatArch/ChatGlance repository, for example `src/chatglance/`, `scripts/`, `docs/`, and `examples/`.
- Content data: repository inventory JSON, caches, and generated snapshots live under the ChatArch-owned runtime at `~/.chatarch/glance/data/` or `~/.chatarch/glance/cache/`.
- Infra/site inventory: the real `server-inventory.yml` and `site-services.yml` are runtime config; generated `chatarch-projects.json`, `projects-page.yml`, `server-status.json`, `server-page.yml`, `site-services.json`, and `site-services-page.yml` are runtime static snapshots, not source.
- Live config: `~/.chatarch/glance/config/glance.yml`; backups go under `~/.chatarch/glance/config/backups/` before replacement.
- Maintenance: `chatglance runtime maintain` is a oneshot command and can be scheduled by `chatarch-glance-maintenance.timer`.
- Install/start: `chatglance runtime install-systemd --start` and `chatglance runtime start` use only user-level systemd and never write `/etc/systemd`.
- A long-running Python wrapper is intentionally not recommended: it couples server lifecycle to content generation and makes service logs, health checks, and rollback worse.

## Safety boundaries

- Commands write explicit output files by default; they do not overwrite a live `glance.yml` by default.
- Do not store or print Glance auth material, password hashes, GitHub tokens, or proxy credentials.
- Runtime binaries, logs, backups, and full live JSON snapshots are not source artifacts.
- If dynamic tables, search, or bilingual UI switching become requirements, add a small static frontend layer later; the current foundation is a Python CLI.


## Subscription quota probe models

Set `CHATGLANCE_ACCOUNT_LIMITS_MODELS` in the collector environment or the refresh service EnvironmentFile to a JSON object mapping exact profile names to available Codex quota probe models, for example `{"example":"supported-codex-model"}`. Refresh scripts inherit this setting.

Only the matching profile quota probe is affected; other profiles, usage GET, credentials, and profile selection remain unchanged. Unset or blank mappings and blank model strings preserve the ChatCRS default. Invalid JSON or non-string model values return a collection error. A model 404 does not establish token expiry; check model availability before rotating credentials.


## Banked Codex resets and scanning

Subscription cards show available cards, next expiry and latest actions. The authenticated popup contains one independent automatic-reset switch per account; there is no global gate or immediate-redemption button. Unknown counts are not zero.

All three conditions must hold: main-window **usage >=95%**, **more than24 hours until natural reset**, and **available cards >0**. Primary/secondary are interpreted by actual timing; extra model limits never trigger. Each profile defaults to disabled; enabling it is that account's only durable execution permission.

```bash
chatglance account-limits collect --profiles "work personal" --output account-limits.json --no-execute-resets
chatglance account-limits render-page --data account-limits.json --output account-limits-page.yml
```

Backend settings come from process environment or the typed ChatGlance ChatEnv schema; explicit CLI options win:

```dotenv
CHATGLANCE_ACCOUNT_LIMITS_RESET_POLICIES={"work":{"enabled":false,"threshold_percent":95,"min_remaining_seconds":86400},"personal":{"enabled":false}}
CHATGLANCE_ACCOUNT_LIMITS_RESET_BASE_URL=https://chatgpt.com/backend-api
```

Set an account's `enabled=true` only after reviewing its policy; it can then consume when all conditions hold. `--no-execute-resets` and `chatglance refresh` remain non-consuming inspection paths. Retire legacy global settings using the migration in [reset controls](docs/reset-controls.md). The optional reset base changes reset endpoints only, preserving the Codex profile usage base. Egress/proxy setup is deployment-owned.

Collection uses GETs for inspection and POSTs for eligible enabled-account redemption, never quota model probes or implicit OAuth refreshes. Missing, failed or stale data cannot authorize consumption. Last-known values are display-only. Account aliases share durable de-duplication state under ChatArch home's `chatglance/` directory. Persist a request ID before POST; at most one card per scan; ambiguous outcomes block further automatic retries. Success requires explicit reset plus credit-count and usage GET readback. Redemption changes the natural reset schedule and never purchases Credits.

Python APIs: `chatglance.codex_collector.collect_account_limits`, `chatglance.codex_resets.scan_profile`, `ResetPolicy`. The published package owns collection; the old script is a thin entrypoint.
