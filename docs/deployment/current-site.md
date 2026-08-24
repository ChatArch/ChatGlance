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
- Runtime website-services reviewed inventory: `/home/zhihong/.chatarch/glance/config/site-services.yml`
- Runtime website-services snapshot: `/home/zhihong/.chatarch/glance/data/site-services.json`
- Runtime website-services page YAML snapshot: `/home/zhihong/.chatarch/glance/data/site-services-page.yml`
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
4. Normalize project type labels for the frontend: early Python packages render as `Python (early)`, but classification is checked against latest-PyPI actual CLI tree evidence. CLI entrypoint count alone is only the visible table surface; stale runtime baseline/category overrides are retained as `reviewed_category` audit evidence and must not demote a complex package such as ChatCRS.
5. Render the current tabs:
   - `最近提交`
   - `PR-issue`
   - `分类`
   - `一览表`
6. Hide unhelpful Disk mountpoints such as snap/loop/tmp/overlay entries.
7. Keep only meaningful local disks:
   - always `/` as `根分区`;
   - include `/home` as `Home` only when `/home` is a distinct mountpoint on the host.
8. With Glance `hide-mountpoints-by-default: true`, every visible mountpoint must explicitly include `hide: false`.
9. Render the reviewed `网站服务` page from fixed runtime config, not from live Nginx auto-discovery. Cards show cover image, description, health status, Uptime detail, and a public jump button; local hostnames remain probe/operator data and must not be displayed on the public-facing page.

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
CHATGLANCE_RUNTIME_HOME=/home/zhihong/.chatarch/glance \
bash scripts/refresh-projects-page.sh
```

The script performs `projects collect`, writes a `project-cli-tree-report.tsv` audit report, runs `projects render-page`, `projects update-config`, and `glance -config ... config:validate`; it stages `.next` JSON/page/report artifacts, validates the candidate config, then backs up/replaces the live JSON, page YAML, CLI-tree TSV, and config together only after validation succeeds. It uses ChatGH's Python API for the authenticated repo list and resolves private-content credentials from explicit token environment variables, the ChatGlance repo-local GitHub credential, the typed active ChatGlance ChatEnv profile, or ChatGH's shared ChatEnv profile in that order. For Python classification, it can run `uvx --from <package>@latest <entrypoint> --tree` or help fallback against published packages; it does not clone/build arbitrary repository source trees. It does not store GitHub tokens or live auth secrets, and it does not perform service-manager actions.

The generated overview includes `刷新时间` / `generated_at` so stale PR/Issue counts are visible. Reusable scripts and code live in ChatArch/ChatGlance; validation snapshots for this work stay under the ChatArch workspace project `projects/chatarch/chatglance/playground/`, not workspace root or `/tmp`.

## Server page live note

Date: 2026-08-11

The live dashboard has three pages:

1. `ChatArch` — ChatArch home / general entry page.
2. `项目` — generated project dashboard.
3. `服务器` — server-status cards generated from a static JSON snapshot.
4. `网站服务` — reviewed service cards with cover images, public jump links, and Uptime status.

The `服务器` page is rendered from `/home/zhihong/.chatarch/glance/data/server-status.json` through an `html` widget. The snapshot is collected by read-only SSH probes using the runtime inventory config at `/home/zhihong/.chatarch/glance/config/server-inventory.yml`. That runtime inventory is the live source of truth for the displayed server list and contains only aliases/display labels/groups/connection labels, not credentials. It records IP, CPU, memory, GPU, mounted filesystem capacity, filtered `lsblk` devices, `Last Reboot`, raw uptime seconds, and the cube `getdevices.sh` disk summary when it can run without installing packages. Displayed collection and reboot timestamps use Beijing time (`+08:00`). The hourly `refresh-live-pages.sh` orchestrator intentionally publishes reviewed offline transitions by default (`CHATGLANCE_ALLOW_SERVER_OFFLINE_REGRESSION=1` unless explicitly overridden), so a timed-out live member is shown as `unreachable` instead of leaving stale `online` resource values on the page.

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

## Website-services page live note

Date: 2026-08-12

The `网站服务` page is rendered from the reviewed runtime inventory at `/home/zhihong/.chatarch/glance/config/site-services.yml`. It records 15 reviewed pages: `bilisum`, `chattea`, `discourse`, `game`, `gitea`, `glance`, `localboard`, `matter`, `nas`, `overleaf`, `revolt`, `share`, `speakr`, `uptime`, and `zulip`.

Intentionally excluded from the first published service page: ChatVideo entries, duplicate/non-target ChatBoard aliases (`board`, `dashboard`, `macboard`), duplicate `mattermost`, unstable `mailpit`, and `pages` because Pages is part of Gitea rather than a standalone card.

The current Gatus/Uptime group is `ChatArch Services`. It probes local vhosts without using public URLs by requesting `http://127.0.0.1/` with the relevant `Host: <service>.local.wzhecnu.cn` header. The Glance card page does not show those local hostnames; it links to the public service URL and to the matching Uptime detail page.

Configured refresh flow for the static website-services snapshot:

```bash
CHATGLANCE_BIN=/home/zhihong/.chatarch/venv/bin/chatglance \
CHATGLANCE_RUNTIME_HOME=/home/zhihong/.chatarch/glance \
CHATGLANCE_SITES_CONFIG=/home/zhihong/.chatarch/glance/config/site-services.yml \
CHATGLANCE_GATUS_DB=/home/zhihong/.chatarch/uptime-gatus/data/gatus.db \
bash scripts/refresh-sites-page.sh
```

Cover images are generated SVG files currently served from Share under `https://share.public.wzhecnu.cn/chatglance-site-covers-20260812/`. The inventory persists those `cover_url` values so ordinary page refreshes do not need to upload images again. If an entry lacks `cover_url`, `chatglance` renders an inline generated SVG fallback.

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
