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

`ChatGlance` is the ChatArch/WZHECNU Glance dashboard generation and operations package. It provides the `chatglance` CLI.

It is not an npm project and does not reimplement the Glance backend. Upstream Glance remains a Go single-binary dashboard server; `ChatGlance` owns reusable Python code for repository inventory rendering, Glance YAML page generation, inline HTML table generation, and safe config transformations.

## Current capabilities

- Render a Glance `项目` page from repository inventory JSON.
- Keep the current tabs limited to `最近提交`, `待处理 PR / Issue`, `分类`, and `一览表`.
- Filter the triage tab to repositories with non-zero PR or Issue counts and sort by `(PR, Issue, recent commit)` descending.
- Replace generated legacy pages: `Projects`, `ChatArch Projects`, and `ChatArch Projects List`.
- Patch Glance `server-stats` to show only the root disk using `hide-mountpoints-by-default: true` plus `mountpoints: /`, so snap/loop mounts do not appear in the Disk popover.
- Maintain a durable runtime with `runtime maintain`: atomic live-config update, backup, validation, and optional restart of a systemd user service only when the rendered config changed.
- Render systemd user units: the main service still starts the upstream Glance Go binary directly; maintenance is an independent oneshot/timer, not a Python server wrapper.

## Quick start

```bash
pip install -e ".[dev]"
chatglance --help
chatglance --tree
chatglance --version
python -m pytest -q
python -m build
```

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

Maintain a durable Glance runtime (default `~/.chatarch/glance`):

```bash
chatglance runtime maintain \
  --runtime-home ~/.chatarch/glance \
  --restart-service chatarch-glance.service
```

Render recommended systemd user units:

```bash
chatglance runtime render-systemd \
  --runtime-home ~/.chatarch/glance \
  --chatglance-bin ~/.chatarch/venv/bin/chatglance \
  --output-dir playground/systemd
```

## Runtime boundary

Recommended topology: **systemd runs Glance directly; chatglance performs maintenance only**.

- Main service: `chatarch-glance.service` executes `~/.chatarch/glance/bin/glance -config ~/.chatarch/glance/config/glance.yml` directly.
- Content data: repository inventory JSON, caches, and generated snapshots live under `~/.chatarch/glance/data/` or `~/.chatarch/glance/cache/`.
- Live config: `~/.chatarch/glance/config/glance.yml`; backups go under `~/.chatarch/glance/config/backups/` before replacement.
- Maintenance: `chatglance runtime maintain` is a oneshot command and can be scheduled by `chatarch-glance-maintenance.timer`.
- A long-running Python wrapper is intentionally not recommended: it couples server lifecycle to content generation and makes systemd restarts, logs, health checks, and rollback worse.

## Safety boundaries

- Commands write explicit output files by default; they do not overwrite a live `glance.yml` by default.
- Do not store or print Glance auth material, password hashes, GitHub tokens, or proxy credentials.
- Runtime binaries, logs, backups, and full live JSON snapshots are not source artifacts.
- If dynamic tables, search, or bilingual UI switching become requirements, add a small static frontend layer later; the current foundation is a Python CLI.
