# Current Glance Site Deployment Record

> Private repository-only record. This file documents the current live ChatArch Glance site and is excluded from public PyPI artifacts by `MANIFEST.in`. `wzhecnu.cn` hostnames are routing labels for the current public/local entry, not the business scope of this dashboard.

Date: 2026-08-09

## Purpose

`ChatGlance` is not primarily a CLI product. The repository records and tests the deployment logic for the current Glance website:

- generated ChatArch project page rules;
- Glance YAML transformations;
- durable runtime layout;
- user-level systemd unit templates;
- live verification notes and safety boundaries.

The `chatglance` command is the helper used to apply these rules to the live runtime.

## Live topology

- Public entry: `https://glance.public.wzhecnu.cn/`
- Local entry: `https://glance.local.wzhecnu.cn/`
- Upstream process: upstream Glance Go binary served on localhost behind Nginx/public-entry routing.
- Runtime home: `/home/zhihong/.chatarch/glance`
- Runtime config: `/home/zhihong/.chatarch/glance/config/glance.yml`
- Runtime project snapshot: `/home/zhihong/.chatarch/glance/data/chatarch-projects.json`
- Runtime project page YAML snapshot: `/home/zhihong/.chatarch/glance/data/projects-page.yml`
- Runtime server-status snapshot: `/home/zhihong/.chatarch/glance/data/server-status.json`
- Runtime server page YAML snapshot: `/home/zhihong/.chatarch/glance/data/server-page.yml`
- Standard ChatArch Python venv for helper CLI: `/home/zhihong/.chatarch/venv`

Live auth settings, password hashes, cookies, proxy credentials, and token-bearing files remain outside Git and are not copied into this repository.

## User-level systemd ownership

The deployment is intentionally user-level, not root/system-level:

- unit directory: `/home/zhihong/.config/systemd/user/`
- main service: `chatarch-glance.service`
- maintenance oneshot: `chatarch-glance-maintenance.service`
- maintenance timer: `chatarch-glance-maintenance.timer`

The main service starts the upstream Glance binary directly. The Python package does not wrap the HTTP server as a long-running process.

Maintenance flow:

```bash
/home/zhihong/.chatarch/venv/bin/chatglance runtime maintain \
  --runtime-home /home/zhihong/.chatarch/glance \
  --restart-service chatarch-glance.service
```

## Managed config rules

`ChatGlance` owns these safe transformations:

1. Replace legacy generated project pages with the current `项目` page.
2. Keep regenerated `项目` immediately after `ChatArch`, before `服务器`, so the live navigation stays `ChatArch` → `项目` → `服务器`.
3. Refresh project inventory data from current ChatGH/GitHub metadata before rendering; the generated page overview includes `刷新时间` / `generated_at` so stale PR/Issue counts are visible.
4. Normalize project type labels for the frontend: early Python packages render as `Python (early)` when that reviewed category is present in the runtime baseline/category overrides. CLI entrypoints alone must not promote or demote a reviewed early category.
5. Render the current tabs:
   - `最近提交`
   - `待处理 PR / Issue`
   - `分类`
   - `一览表`
6. Hide unhelpful Disk mountpoints such as snap/loop/tmp/overlay entries.
7. Keep only meaningful local disks:
   - always `/` as `根分区`;
   - include `/home` as `Home` only when `/home` is a distinct mountpoint on the host.
8. With Glance `hide-mountpoints-by-default: true`, every visible mountpoint must explicitly include `hide: false`.

Correct Disk config shape:

```yaml
- type: server-stats
  servers:
    - type: local
      name: rexpc
      hide-swap: true
      hide-mountpoints-by-default: true
      mountpoints:
        "/":
          name: 根分区
          hide: false
```

Do not put `hide-mountpoints-by-default` on the widget root; upstream Glance documents it as a local-server property.

## Disk `n/a` incident note

Observed issue:

- The live Disk card rendered `n/a`.
- Live config had `hide-mountpoints-by-default: true` but selected mountpoints only had `name` and no `hide: false`.
- Glance therefore hid even the selected `/` mountpoint.

Fix committed for `ChatGlance==0.1.2`:

- `patch_server_stats_mountpoints()` writes `{name: <label>, hide: false}` for every selected mountpoint.
- `runtime maintain` discovers meaningful mountpoints on the live host.
- `/home` is not added on the current host because it is not a separate mountpoint from `/`.

## Project page live note

Date: 2026-08-11

The `项目` page is rendered from the ChatArch-owned runtime snapshot at `/home/zhihong/.chatarch/glance/data/chatarch-projects.json`. Refreshes should use the bundled ChatGlance repo script, not ad-hoc files outside the ChatArch/ChatGlance project:

```bash
CHATGLANCE_BIN=/home/zhihong/.chatarch/venv/bin/chatglance \
CHATGH_BIN=/home/zhihong/.chatarch/venv/bin/chatgh \
CHATGLANCE_RUNTIME_HOME=/home/zhihong/.chatarch/glance \
bash scripts/refresh-projects-page.sh
```

The script performs `projects collect`, `projects render-page`, `projects update-config`, and `glance -config ... config:validate`; it stages `.next` JSON/page artifacts, validates the candidate config, then backs up/replaces the live JSON, page YAML, and config together only after validation succeeds. It uses ChatGH for the authenticated repo list and either token environment variables or the ChatGlance repo-local GitHub credential for private repository contents. It does not store GitHub tokens or live auth secrets, and it does not perform service-manager actions.

The generated overview includes `刷新时间` / `generated_at` so stale PR/Issue counts are visible. Reusable scripts and code live in ChatArch/ChatGlance; validation snapshots for this work stay under the ChatArch workspace project `projects/chatarch/chatglance/playground/`, not workspace root or `/tmp`.

## Server page live note

Date: 2026-08-11

The live dashboard has three pages:

1. `ChatArch` — ChatArch home / general entry page.
2. `项目` — generated project dashboard.
3. `服务器` — server-status cards generated from a static JSON snapshot.

The `服务器` page is rendered from `/home/zhihong/.chatarch/glance/data/server-status.json` through an `html` widget. The snapshot is collected by read-only SSH probes using the runtime inventory config at `/home/zhihong/.chatarch/glance/config/server-inventory.yml`. That runtime inventory is the live source of truth for the displayed server list and contains only aliases/display labels/groups/connection labels, not credentials. It records IP, CPU, memory, GPU, mounted filesystem capacity, filtered `lsblk` devices, `Last Reboot`, raw uptime seconds, and the cube `getdevices.sh` disk summary when it can run without installing packages. Displayed collection and reboot timestamps use Beijing time (`+08:00`).

Collection boundaries:

- no package installation;
- no `sudo` writes;
- no server restart except the final Glance user service restart after config validation;
- no token, private key, proxy, or full SSH config exposure;
- displayed IPs follow the SSH connection endpoint: cube aliases use the locally resolved `172.*` target, public hosts use their configured public HostName IP;
- common virtual VGA adapters on ordinary public VMs are not counted as GPUs, so those cards render `GPU: NULL`;
- collapsed cards show IP, CPU, memory, disk, and status only;
- GPU details are kept only in the card's expandable details section;
- expanded system details include `Last Reboot` and raw `uptime_seconds` from the read-only Linux probe;
- `lsblk` loop/rom/zram/snap/tmpfs/proc/sysfs noise is filtered;
- retired, duplicate, local-only, and explicitly user-excluded SSH aliases are excluded from the server page inventory.

Configured refresh flow for the static snapshot:

```bash
CHATGLANCE_BIN=/home/zhihong/.chatarch/venv/bin/chatglance \
CHATGLANCE_RUNTIME_HOME=/home/zhihong/.chatarch/glance \
CHATGLANCE_INFRA_CONFIG=/home/zhihong/.chatarch/glance/config/server-inventory.yml \
bash scripts/refresh-server-status.sh
```

Manual command equivalence is documented in `docs/infra.md`: `chatglance servers collect --inventory-config ...`, `render-page --inventory-config ...`, and `update-config --inventory-config ...`, followed by `glance -config ... config:validate`; the bundled script stages `.next` JSON/page artifacts and replaces JSON/page/config together only after validation. Service-manager actions stay outside the bundled refresh script and run only from the scheduler/operator boundary when needed.

The repeatable PR path now records the inventory/config/refresh mechanism. Live changes should be applied through a validated candidate config, with a timestamped backup before replacement and a user-service lifecycle action only after validation succeeds.

Current reviewed live membership after the 2026-08-12 refresh is 10 reachable
servers: 7 cube hosts plus `rex.aliyun`, `elion.newaliyun`, and `rex.newazure`.
`tencent.am` is intentionally excluded from the Glance server page; it should not
be pulled in by default candidates or historical snapshots unless explicitly
re-added to the runtime inventory.

## Verification checklist

After deployment, verify:

```bash
/home/zhihong/.chatarch/venv/bin/chatglance --version
/home/zhihong/.chatarch/venv/bin/chatglance runtime maintain --runtime-home /home/zhihong/.chatarch/glance
/home/zhihong/.chatarch/glance/bin/glance -config /home/zhihong/.chatarch/glance/config/glance.yml config:validate
/home/zhihong/.chatarch/venv/bin/chatglance runtime status
curl --noproxy '*' -I http://127.0.0.1:5678/
```

Then verify public routing:

- `https://glance.public.wzhecnu.cn/` redirects to `/login`.
- `/login` returns the Glance login page.
- Public response bodies must not leak `glance.local.wzhecnu.cn`.
- Disk should show a real percentage for the selected root disk, not `n/a`.

## Safety boundary

- This private repository may describe live topology and sanitized operational paths.
- Public package artifacts must not ship this exact deployment record.
- Live Glance auth/config secrets remain in the runtime home only.
- Reports and docs must redact any password hash, token, cookie, proxy credential, and secret-bearing file content.
