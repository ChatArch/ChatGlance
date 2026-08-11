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
- Runtime inventory snapshot: `/home/zhihong/.chatarch/glance/data/chatarch-projects.json`
- Runtime server-status snapshot: `/home/zhihong/.chatarch/glance/data/server-status.json`
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
2. Render the current tabs:
   - `最近提交`
   - `待处理 PR / Issue`
   - `分类`
   - `一览表`
3. Hide unhelpful Disk mountpoints such as snap/loop/tmp/overlay entries.
4. Keep only meaningful local disks:
   - always `/` as `根分区`;
   - include `/home` as `Home` only when `/home` is a distinct mountpoint on the host.
5. With Glance `hide-mountpoints-by-default: true`, every visible mountpoint must explicitly include `hide: false`.

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

## Server page live note

Date: 2026-08-11

The live dashboard has three pages:

1. `ChatArch` — ChatArch home / general entry page.
2. `项目` — generated project dashboard.
3. `服务器` — server-status cards generated from a static JSON snapshot.

The `服务器` page is rendered from `/home/zhihong/.chatarch/glance/data/server-status.json` through an `html` widget. The snapshot is collected manually by SSH probes and audited against the local SSH configuration. It records IP, CPU, memory, GPU, mounted filesystem capacity, filtered `lsblk` devices, and the cube `getdevices.sh` disk summary when it can run without installing packages.

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
- `azure.cn`, `essay.newaliyun`, `rex.ctyun`, and `zhihong.tencent` are excluded from the default server page inventory.

Manual update flow for the static snapshot:

```bash
chatglance servers collect --default-candidates --output server-status.json
chatglance servers render-page --data server-status.json --output server-page.yml
chatglance servers update-config --data server-status.json --config glance.yml --output glance.yml.candidate
/home/zhihong/.chatarch/glance/bin/glance -config glance.yml.candidate config:validate
```

For the first live install, the validated page was appended to the runtime config directly, because this was a live-page task and the formal PR/PyPI release was intentionally deferred.

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
