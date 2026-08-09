# Changelog

## 0.1.1 - 2026-08-09

User-level systemd service management release.

- Add `runtime install-systemd` to write, verify, daemon-reload, enable, and optionally start user-level Glance service/timer units.
- Add `runtime start` to start the current page through `systemctl --user`.
- Add `runtime status` for safe service/timer readback fields.
- Keep the service topology user-level only: `~/.config/systemd/user`, `systemd-analyze --user verify`, and `systemctl --user`.

## 0.1.0 - 2026-08-09

First workflow-verified ChatArch release target.

- Add reusable Glance `项目` page generation from repository inventory JSON.
- Keep project tabs focused on `最近提交`, `待处理 PR / Issue`, `分类`, and `一览表`.
- Filter triage to repositories with non-zero PR/Issue counts.
- Patch Glance `server-stats` disk display to root-only with `hide-mountpoints-by-default`.
- Add `runtime maintain` for durable service-home maintenance.
- Add `runtime render-systemd` for direct Glance service plus chatglance maintenance oneshot/timer units.

## 0.0.1 - 2026-08-09

Initial PyPI placeholder/name-claim target for `ChatGlance` / `chatglance`.
