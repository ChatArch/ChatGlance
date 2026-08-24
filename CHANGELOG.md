# Changelog

## Unreleased

- Publish account-limits refreshes even when one Codex profile fails, preserving the last successful quota window while marking the current profile status as expired/unavailable.
- Add a top-level account-limits collection status banner and per-profile credential status lines without exposing token values.

## 0.1.8 - 2026-08-23

Project refresh timer and PR-issue label patch.

- Run source-based live refreshes with the ChatArch virtualenv Python when available so user-level timers do not import stale system-site ChatStyle packages.
- Rename the `项目` page triage tab and overview label from `待处理 PR / Issue` to `PR-issue`.

## 0.1.7 - 2026-08-22

Project detail CLI comment and switch release.

- Preserve inline `# ...` comments from `--tree-brief` in stored `brief_trees` and project detail code blocks.
- Show CLI and ENV detail modules behind a lightweight clickable switch when a project has ChatEnv/ENV metadata.

## 0.1.6 - 2026-08-22

Project detail brief CLI tree release.

- Prefer `--tree-brief` when collecting actual CLI tree evidence and render the brief CLI tree as a code block in project detail cards.

## 0.1.5 - 2026-08-21

ChatArch CLI runtime and typed environment alignment release.

- Replace the package-local Click tree renderer with ChatStyle `add_tree_option()` and expose registered `--tree` / `--tree-brief` output from the explicit `chatglance` root.
- Add bounded `chatstyle>=0.2.0,<0.3.0` and `chatenv>=0.2.10,<0.3.0` runtimes plus a typed, sensitive ChatGlance token profile at ChatEnv's storage path.
- Document command side effects and secret boundaries, keep checked-in full/brief trees aligned with the real registry, and add installed CLI/build/package checks to the Python 3.10-3.12 CI matrix.

## 0.1.4 - 2026-08-21

Project category count display patch.

- Show repository counts in each `分类` group title and align category ordering with the project table.

## 0.1.3 - 2026-08-21

Project page metadata, authenticated GitHub refresh, and live dashboard detail UX release.

- Reuse ChatGH's ChatEnv `GITHUB_ACCESS_TOKEN` as the final ChatGlance GitHub API token fallback after explicit env vars and repo-local git credentials, keeping project refreshes authenticated even outside the ChatGlance checkout.
- Add native-click `详情` popover cards to the `项目` inventory table with registered ChatEnv ENV keys, descriptions, sensitivity flags, and no values; dependency-only ChatEnv projects stay out of the ENV detail section.
- Sort the `项目` table by category with Python packages first, Node/npm packages next, service/docs/other projects after that, and Python early packages last.
- Add `chatglance servers --inventory-config` support for Infra/server inventory YAML: alias selection, exclusions, labels, collection defaults, and page metadata.
- Add `docs/infra.md`, `examples/server-inventory.example.yml`, and `scripts/refresh-server-status.sh` to document and automate the external static-data refresh path.
- Document which Infra content is source/config versus generated runtime data, including `server-status.json`, `server-page.yml`, and candidate Glance config refreshes.
- Render server collection timestamps, `Last Reboot`, generated snapshot times, and refresh-script backup names in Beijing time (`+08:00`).
- Add `docs/quickstart.md` for new-machine setup where Glance frontend configuration stays primary and the CLI remains a management helper.
- Add `chatglance projects collect` and `scripts/refresh-projects-page.sh` so the `项目` page data can be refreshed from current ChatGH/GitHub metadata before rendering, including private repository manifest reads via token environment variables or repo-local GitHub credentials.
- Add visible `刷新时间` / `generated_at` information to the generated `项目` page overview so PR/Issue data freshness is explicit.
- Normalize early Python package display on the `项目` page to `Python (early)` while deriving Python maturity from latest-PyPI actual CLI tree/help evidence; stale early/template categories are retained only as reviewed audit evidence and cannot demote complex packages such as ChatCRS.
- Keep regenerated `项目` pages immediately after the `ChatArch` home page, before `服务器`, instead of appending them to the end of the navigation.
- Add reviewed `网站服务` page generation with card layout, generated/hosted SVG cover support, public jump links, Uptime detail links, fixed `site-services.yml` inventory, and `scripts/refresh-sites-page.sh` candidate-validation workflow.

## 0.1.2 - 2026-08-09

Disk mountpoint visibility hotfix and deployment-record reframing.

- Fix Glance Disk `n/a` by writing `hide: false` for selected mountpoints when `hide-mountpoints-by-default: true` is enabled.
- Keep `hide-mountpoints-by-default` on local server entries instead of the widget root, matching upstream Glance docs.
- Let `runtime maintain` use meaningful local mountpoints: `/` always, `/home` only when it is an actual separate mountpoint.
- Reframe the repository as Glance website deployment source/records first; `chatglance` CLI remains an auxiliary management helper.

## 0.1.1 - 2026-08-09

User-level systemd service management release.

- Add `runtime install-systemd` to write, verify, daemon-reload, enable, and optionally start user-level Glance service/timer units.
- Add `runtime start` to start the current page through `systemctl --user`.
- Add `runtime status` for safe service/timer readback fields.
- Keep the service topology user-level only: `~/.config/systemd/user`, `systemd-analyze --user verify`, and `systemctl --user`.

## 0.1.0 - 2026-08-09

First workflow-verified ChatArch release target.

- Add reusable Glance `项目` page generation from repository inventory JSON.
- Keep project tabs focused on `最近提交`, `PR-issue`, `分类`, and `一览表`.
- Filter triage to repositories with non-zero PR/Issue counts.
- Patch Glance `server-stats` disk display to root-only with `hide-mountpoints-by-default`.
- Add `runtime maintain` for durable service-home maintenance.
- Add `runtime render-systemd` for direct Glance service plus chatglance maintenance oneshot/timer units.

## 0.0.1 - 2026-08-09

Initial PyPI placeholder/name-claim target for `ChatGlance` / `chatglance`.
