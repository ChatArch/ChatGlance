# Refresh Scheduling and Settings Design

This document is a design proposal. It does not change the current live refresh behavior by itself.

## Current live behavior

The live ChatArch Glance site is refreshed by local user-level systemd units on `zhihong.oray`:

- `chatarch-glance-refresh-pages.timer`
  - `OnUnitActiveSec=1h`
  - runs `chatarch-glance-refresh-pages.service`
- `chatarch-glance-refresh-pages.service`
  - working directory: the ChatGlance checkout
  - runs `scripts/refresh-live-pages.sh`
- `scripts/refresh-live-pages.sh`
  - runs page refresh scripts such as `refresh-server-status.sh`, `refresh-account-limits-page.sh`, and `refresh-projects-page.sh`
  - restarts `chatarch-glance.service` once when any generated page changed
- `chatarch-glance-maintenance.timer`
  - separate 30 minute runtime maintenance timer

This is not dynamic logic inside the upstream Glance frontend. Glance serves a generated `glance.yml`; ChatGlance refresh scripts produce static JSON/YAML snapshots and then reload the Glance service.

## Requirement

We want a UI-visible settings entry where an operator can control refresh timing per page/tag, for example:

- `项目`: every 1 hour
- `服务器`: every 15 minutes
- `网站服务`: every 10 minutes
- `订阅详情`: every 30 minutes

At the same time, the real refresh scripts should stay machine-local and runtime-owned. Different servers can need different commands, environment, paths, proxies, and wrappers; those local choices should not be forced into the PyPI package or public examples.

## Design principle

Use the same split as the Infra inventory design:

1. The ChatGlance repository owns the schema, validation rules, docs, safe rendering, and examples.
2. The live runtime owns the concrete refresh schedule config and the actual scripts.
3. The web UI may edit only safe schedule fields, not arbitrary shell commands.

Recommended live runtime layout:

```text
~/.chatarch/glance/
  config/glance.yml
  config/refresh-schedule.yml        # runtime-owned schedule source of truth
  data/refresh-state.json            # generated last/next run state
  refresh.d/projects.sh              # runtime-owned wrappers
  refresh.d/servers.sh
  refresh.d/sites.sh
  refresh.d/account-limits.sh
  logs/refresh-scheduler.log
```

A sanitized example lives at `examples/refresh-schedule.example.yml`.

## Why not put the scripts in the package?

Do not make the package own all live scripts:

- local refresh commands often depend on host paths, local venvs, SSH aliases, proxy behavior, and live runtime inventory files;
- scripts may need local operational edits before they are generalized;
- storing concrete script bodies in the package would make runtime flexibility and rollback harder;
- web editing a raw script is unsafe.

The package can own helper templates and validation, but the concrete command should be runtime config or a runtime-owned wrapper script.

## Proposed schedule config contract

Each job has stable identity and human-facing metadata plus a runtime command:

```yaml
version: 1
settings:
  timezone: Asia/Shanghai
  default_timeout: 20m
  lock_file: logs/refresh-scheduler.lock
  state_file: data/refresh-state.json
  restart_service: chatarch-glance.service

jobs:
  - id: projects
    label: 项目
    page: 项目
    tag: page:projects
    enabled: true
    interval: 1h
    command: refresh.d/projects.sh
    working_directory: /home/zhihong/Playground/core/ChatGlance
    timeout: 20m
    restart_on_change: true
    editable:
      - enabled
      - interval

  - id: servers
    label: 服务器
    page: 服务器
    tag: page:infra
    enabled: true
    interval: 15m
    command: refresh.d/servers.sh
    timeout: 3m
    restart_on_change: true
    editable:
      - enabled
      - interval
```

Rules:

- `id` is immutable once created; it keys state, logs, and UI forms.
- `label`, `page`, and `tag` are display/grouping metadata.
- `interval` accepts reviewed durations such as `5m`, `15m`, `1h`, `6h`, or cron-like schedules if later implemented.
- `command` is runtime-relative or absolute and is edited by the operator on the server, not by the web UI.
- `editable` declares what the web UI may change. The first implementation should allow only `enabled` and `interval`.
- job commands must not contain secrets; credentials remain in ChatEnv profiles, SSH config, service environment, or runtime-only files.

## Scheduler options

### Option A: read-only settings page

Add a generated `刷新设置` page that shows:

- job label;
- enabled state;
- interval;
- last run;
- next due time;
- last result;
- script path or wrapper name.

Operators still edit `refresh-schedule.yml` on the server. This is safest and easiest, but it is not a web-edit button.

### Option B: config-driven scheduler, no web writes

Replace the single hourly `chatarch-glance-refresh-pages.timer` with a frequent user timer, for example once per minute:

```ini
[Timer]
OnBootSec=1min
OnUnitActiveSec=1min
Persistent=true
Unit=chatarch-glance-refresh-scheduler.service
```

The service runs a ChatGlance helper such as:

```bash
chatglance refresh run-due \
  --runtime-home ~/.chatarch/glance \
  --schedule-config config/refresh-schedule.yml
```

The helper reads `refresh-schedule.yml`, checks `refresh-state.json`, runs only due jobs, serializes execution through a lock, and restarts Glance once if any job changed generated config.

This takes over the current cron/timer responsibility while keeping scripts runtime-owned.

### Option C: protected operator settings UI

Add a local operator service, for example `chatarch-glance-operator.service`, bound to loopback. The Glance page gets a `设置` button linking to that operator UI or embedding it if Glance supports the required HTML/iframe behavior.

The operator API can expose safe actions:

- `GET /api/refresh/jobs`
- `PATCH /api/refresh/jobs/{id}` with only `enabled` and `interval`
- `POST /api/refresh/jobs/{id}/run` for manual run, if allowed

Security requirements:

- bind only to `127.0.0.1` or a private socket;
- expose through the existing authenticated reverse proxy, not directly to the public internet;
- validate every edit against the schema and allowed `editable` fields;
- write `refresh-schedule.yml` atomically with a timestamped backup;
- never accept raw shell commands from the browser;
- record an audit line for every web edit/manual run;
- keep service-manager actions in user-level systemd only.

This is the only design that gives a real web-edit button. It is more complex than a static Glance widget because upstream Glance itself is not currently the write-capable backend.

## Recommended rollout

1. **Design PR only**
   - add this document and a sanitized `refresh-schedule.example.yml`;
   - do not change live timers or publish a new release.
2. **Read-only status PR**
   - parse `refresh-schedule.yml`;
   - render a `刷新设置` or `设置` card/page showing intervals and last/next run state;
   - keep manual YAML edits.
3. **Scheduler PR**
   - add `chatglance refresh run-due`;
   - add a systemd user unit template that runs once per minute;
   - migrate the current hourly `chatarch-glance-refresh-pages.timer` to the config-driven scheduler.
4. **Operator UI PR**
   - add a small authenticated local operator service and settings button;
   - support only safe fields first: `enabled` and `interval`;
   - optionally add manual run buttons after audit logging is in place.

## Open questions

- Should the settings entry be a standalone `设置` page, a `刷新设置` page, or a button on each generated page?
- Should jobs be grouped by page (`项目`, `服务器`, `网站服务`) or by tag (`page:projects`, `infra`, `external-status`)?
- Should manual run be allowed from the first editable UI, or only after interval editing is stable?
- Should the first scheduler use a one-minute polling timer or generated per-job systemd timers?

The current recommendation is a one-minute config-driven scheduler because it avoids regenerating systemd unit files every time an interval changes. It also keeps the web operator API from needing to call `systemctl --user daemon-reload` after every edit.
