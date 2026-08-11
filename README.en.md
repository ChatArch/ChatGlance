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

`ChatGlance` is the private ChatArch/WZHECNU repository for Glance website deployment source and operations records. It preserves the current site's page-generation logic, configuration transformations, user-level service templates, verification notes, and safety boundaries; the `chatglance` CLI is only the helper entrypoint for applying those rules.

It is not an npm project and does not reimplement the Glance backend. Upstream Glance remains a Go single-binary dashboard server; `ChatGlance` owns reusable Python code and private deployment records for repository inventory rendering, Glance YAML page generation, inline HTML table generation, selected Disk mountpoint display, and user-level runtime maintenance.

## Repository contents

- `src/chatglance/`: helper code for page generation, Glance YAML patching, runtime maintenance, and user-level systemd unit rendering/installation.
- `tests/`: regression tests for project pages, Disk mountpoint visibility, runtime/systemd helpers, and release workflow contracts.
- `docs/infra.md`: configuration mechanism, external data-generation chain, refresh workflow, and cron/timer template for the Infra/`服务器` page.
- `docs/deployment/current-site.md`: private repository-only deployment record for the current live Glance site. It is excluded from public package artifacts.
- `examples/server-inventory.example.yml`: sanitized inventory config template. The real inventory belongs in the runtime config directory.
- `scripts/refresh-server-status.sh`: external refresh script template for manual runs, cron, or a systemd user timer.
- `README.md` / `README.en.md` / `CHANGELOG.md`: collaboration and package-facing entry points; do not include live auth, tokens, password hashes, proxy credentials, or secret-bearing files.

## Current capabilities

- Render a Glance `项目` page from repository inventory JSON.
- Keep the current tabs limited to `最近提交`, `待处理 PR / Issue`, `分类`, and `一览表`.
- Filter the triage tab to repositories with non-zero PR or Issue counts and sort by `(PR, Issue, recent commit)` descending.
- Replace generated legacy pages: `Projects`, `ChatArch Projects`, and `ChatArch Projects List`.
- Patch Glance `server-stats` to show only selected meaningful disks. The current live policy keeps `/` and adds `/home` only when it is a separate mountpoint; each visible entry is written with `hide: false` so the Disk card does not render `n/a`, while snap/loop/tmp overlays stay hidden.
- Select SSH aliases from an Infra inventory YAML, collect a read-only static `server-status.json`, and render the Glance `服务器`/Infra page from that snapshot.
- Keep collapsed server cards limited to IP/CPU/memory/disk/status while GPU, mountpoints, filtered `lsblk`, safe `getdevices` summaries, and `Last Reboot` stay in expandable details.
- Maintain a durable runtime with `runtime maintain`: atomic live-config update, backup, and validation; service lifecycle actions stay outside the default docs examples.
- Render and install user-level systemd units: the main service still starts the upstream Glance Go binary directly; maintenance is an independent oneshot/timer, not a Python server wrapper.
- Install, enable, start, and read back the current Glance page user service/timer from the CLI.

## Quick start

```bash
pip install -e ".[dev]"
chatglance --help
chatglance --tree
chatglance --version
python -m pytest -q
python -m build
```

The recommended Infra/`服务器` refresh entry point is the external script, not hand-editing JSON:

```bash
cp examples/server-inventory.example.yml ~/.chatarch/glance/config/server-inventory.yml
$EDITOR ~/.chatarch/glance/config/server-inventory.yml

CHATGLANCE_BIN=~/.chatarch/venv/bin/chatglance \
CHATGLANCE_RUNTIME_HOME=~/.chatarch/glance \
CHATGLANCE_INFRA_CONFIG=~/.chatarch/glance/config/server-inventory.yml \
bash scripts/refresh-server-status.sh
```

The script calls `chatglance servers collect/render-page/update-config`, writes a candidate config, runs `glance config:validate`, then backs up/replaces the live config when content changed; service-manager actions stay in the outer cron/systemd wrapper or a manual operator step. See [`docs/infra.md`](docs/infra.md) for the full mechanism.

## CLI examples

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
- Content data: repository inventory JSON, caches, and generated snapshots live under `~/.chatarch/glance/data/` or `~/.chatarch/glance/cache/`.
- Infra inventory: the real `server-inventory.yml` is runtime config that defines which SSH aliases are marked as Infra; generated `server-status.json` / `server-page.yml` are external snapshots, not source.
- Live config: `~/.chatarch/glance/config/glance.yml`; backups go under `~/.chatarch/glance/config/backups/` before replacement.
- Maintenance: `chatglance runtime maintain` is a oneshot command and can be scheduled by `chatarch-glance-maintenance.timer`.
- Install/start: `chatglance runtime install-systemd --start` and `chatglance runtime start` use only user-level systemd and never write `/etc/systemd`.
- A long-running Python wrapper is intentionally not recommended: it couples server lifecycle to content generation and makes service logs, health checks, and rollback worse.

## Safety boundaries

- Commands write explicit output files by default; they do not overwrite a live `glance.yml` by default.
- Do not store or print Glance auth material, password hashes, GitHub tokens, or proxy credentials.
- Runtime binaries, logs, backups, and full live JSON snapshots are not source artifacts.
- If dynamic tables, search, or bilingual UI switching become requirements, add a small static frontend layer later; the current foundation is a Python CLI.
