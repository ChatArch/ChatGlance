# Project Page Refresh Contract

The Glance `项目` page is generated from a reviewed ChatArch repository inventory. It is not a raw dump of command trees or arbitrary repository manifests.

## Displayed content

The page contains:

1. **概览**
   - visible repository count;
   - total repositories with open PRs/issues;
   - visible `刷新时间` from the generated inventory `generated_at` field;
   - a note that the snapshot is generated locally and contains no credentials.
2. **最近提交**
   - repositories sorted by latest pushed/updated time.
3. **PR-issue**
   - only repositories with open PRs or open issues.
4. **分类**
   - reviewed project categories, including the short label `Python (early)` for early Python packages;
   - group titles include repository counts, for example `Python 包 (31)`;
   - category group order is `Python 包`, `Node / npm 包`, service/docs/other projects, then `Python (early)`;
   - Python package early/non-early classification is checked against the latest published package's actual CLI tree, not just entrypoint count or stale overrides.
5. **一览表**
   - repository link and a native-click detail button;
   - authenticated/private rendering adds an explicit `可见性` badge: `Public` only for literal `private: false`, `Private` only for literal `private: true`, and `Unknown` for missing or malformed visibility;
   - open PR count;
   - open issue count;
   - version;
   - type/category;
   - ChatEnv/ENV summary badge only when schema metadata or `chatenv.configs` registration exists;
   - package CLI entrypoint;
   - actual CLI tree business-command evidence in the generated JSON/TSV review artifact;
   - docs link candidate;
   - an explicit reviewed Web link immediately after docs, or `—` when no valid Web metadata is configured;
   - latest commit date;
   - table category order is `Python 包` first, `Node / npm 包` next, then service/docs/other projects, with `Python (early)` projects last.
6. **仓库详情卡片**
   - GitHub/docs/Web links, description, version/category/PR/Issue/commit metrics;
   - authenticated/private rendering repeats the explicit `可见性` badge (`Public`, `Private`, or `Unknown` under the same literal-boolean rule);
   - package CLI entrypoints plus a scrollable brief CLI tree code block when actual tree evidence is available; inline `# ...` comments from `--tree-brief` are preserved;
   - projects with ChatEnv/ENV metadata expose CLI and ENV modules behind a lightweight click switch so the CLI tree does not push ENV details out of view;
   - ChatEnv schema table when a provider/schema is registered: schema, ENV key, description, sensitivity flag, and default-presence flag only;
   - dependency-only ChatEnv projects are omitted from the ENV detail section until they register a provider/schema.

## Public/private projection contract

### Single-origin optional login (candidate only)

`build_single_origin_optional_login_config(full_config, full_inventory)` and `chatglance access render-single-origin-optional-login --config PRIVATE.yml --inventory FULL.json --output CANDIDATE.yml` generate one **private** Glance config for the patched core. The candidate must not be committed or served as an asset. Use an existing, non-symlink output directory; the command writes atomically at `0600`, refuses symlinks and input/output aliases, and reports redacted errors without printing the config. Validate the candidate with the patched Glance binary's `config:validate` before any operator-managed deployment. This command does not switch a service, host, scheduler, or account.

The synthetic core integration test is opt-in: set test-only `CHATGLANCE_TEST_GLANCE_BIN` to an executable patched Glance binary when running `pytest tests/test_optional_login.py`. Unset skips only the binary validation test; an explicitly configured missing or non-executable path fails. Do not record local binary paths in source, docs, or CI defaults.

The existing `ChatArch` and `项目` pages keep their order, names, and slugs (including `/项目`). Their ordinary `columns` contain only a static guest home and the literal-Public allowlist; `authenticated-columns` contain the original home widgets and fully rendered project rows with Public/Private/Unknown badges. Both pages explicitly set `public: true`; every other page is private. Glance selects the columns server-side using the existing auth session. The full inventory and config stay server-side, never as guest assets. Auth and trusted server routing are preserved; document head, branding, and theme are **not** inherited into the guest shell. Nonempty document head, assets-path, or head-widgets on either public page are rejected instead of silently making private content guest-visible. Review any new global or shared assets separately before deployment.

`projects update-config`, `runtime maintain`, and package-owned `refresh projects` detect the trusted pair of public pages with authenticated columns and regenerate both project layouts; they do not rely on inventory audience metadata. Malformed or partial mode fails closed. Existing non-optional configs retain their ordinary private rendering. After candidate installation, operators still need to validate anonymous/authenticated navigation, direct private URLs, content APIs, logout and cache headers on the actual site; generating a candidate alone does not establish those gates.

The authenticated page keeps the full inventory and is the backward-compatible default for `build_projects_page`. The anonymous boundary always receives the full inventory and projects it itself:

1. `build_projects_page(full_inventory, audience="public")` calls the trusted projector at render time, retains only rows whose source `private` flag is exactly `false`, and emits no visibility column, badge, or private row. A markerless or edited detached artifact is not trusted as full input.
2. `chatglance.access.project_public_inventory(full_inventory)` separately produces the JSON publication artifact. Its explicit row schema contains only the displayed name, validated repository/docs/Web URLs, description, PR/Issue counts, dates, normalized category, and allowlisted version fields. It omits `full_name`, visibility, CLI, Env, package/evidence, collector fields, the entire source block, and all arbitrary fields. Counts and categories are recomputed only from retained rows.

`chatglance.access.build_public_glance_config` passes the full inventory through that render boundary and reconstructs an anonymous config with only an explicit static `ChatArch` home and the projected `项目` page. It never inherits `auth`, the private server mapping, existing home widgets, or any site/account/server page. A public `server` mapping is included only when the caller explicitly supplies a plain validated `host` and `port` mapping.

Repository, docs, and reviewed Web links render only when they are well-formed external HTTPS URLs with no credentials and no local/private host. Invalid links are omitted from bookmarks, table cells, and detail cards rather than escaped into clickable HTML.

The thin file adapter writes candidates only to explicit paths:

```bash
chatglance access render-public \
  --config /path/to/full-glance.yml \
  --inventory /path/to/full-projects.json \
  --config-output /path/to/candidate/public-glance.yml \
  --inventory-output /path/to/candidate/public-projects.json
```

Create one trusted output directory first and place both distinct candidate paths directly in it. The directory and targets must not be symlinks; the directory must already exist, and existing targets must be regular files. The command fully stages and fsyncs mode-`0600` files in that directory, atomically replaces both ordinary candidates, and restores/removes the first output if publishing the second fails. Parse and filesystem failures are reported with redacted Click errors.

Add `--host HOST --port PORT` together only when the public candidate should contain an explicit server mapping. The command validates its inputs and builds both candidates before creating either output, prints only output paths plus public repository/page counts, and does not publish to live runtime, refresh, restart, or modify service state.

## Refresh rules

- `ChatGlance` must appear on the project page when it is visible in the ChatArch repository list.
- Version display is **PyPI-only**. Do not use GitHub tags, GitHub releases, `pyproject.toml`, `package.json`, or local manifests as version sources for the page.
- CLI display in the table remains **entrypoint-only**. For Python packages this means `project.scripts` / `project.gui-scripts`; for Node packages this means `package.json` `bin` entries. Do not expand Click/Typer/npm subcommands into the compact table cell.
- Python package classification uses actual CLI tree evidence when available: the refresh installs the latest PyPI package with `uvx --from <package>@latest <entrypoint> --tree-brief` first, falls back to `--tree`/`--help`, and counts non-option business command nodes. `--help`, `--version`, `--tree`, and `--tree-brief` are global options, not business commands.
- `Python (early)` is for placeholder/scaffold/trivial packages: no business subcommands in the actual CLI tree, or explicit placeholder/scaffold/PyPI-name-registration evidence. A package with real business subcommands is `Python 包` even if an older baseline/override marked it as early.
- `--baseline-data` may preserve reviewed categories for projects without stronger current tree evidence, but stale early overrides must not demote complex CLI packages such as ChatCRS.
- `--baseline-data` is also the only source of reviewed project Web links. A repository override must contain `web: {"url": "https://...", "kind": "..."}`. Only public HTTPS URLs without credentials and one of the reviewed kinds (`workbench`, `observatory`, `board`, `file-gateway`, `hub`, `dashboard`, `static-site`, `app`) are preserved; all other fields are discarded. Web URLs are never inferred from repository names, docs, CLI commands, ChatSite, or Hub relationships.
- ChatEnv metadata is extracted from `[project.entry-points."chatenv.configs"]` target modules and `EnvField` declarations. The generated inventory stores only schema names, ENV keys, descriptions, sensitivity flags, and whether a default exists; it must not store `.env` values or default literal values.
- GitHub API file/content reads must stay authenticated when possible. Token resolution order is explicit `CHATGLANCE_GITHUB_TOKEN` / `GITHUB_TOKEN` / `GH_TOKEN`, then repo-local git `extraHeader`, then the typed active ChatGlance profile at ChatEnv's storage path, then ChatGH's ChatEnv `GitHubConfig.GITHUB_ACCESS_TOKEN`.
- Tokens, cookies, auth headers, password hashes, and credentials must stay out of generated JSON/YAML and repository docs.

## Refresh script

The repository-owned script is:

```text
scripts/refresh-projects-page.sh
```

Recommended live invocation:

```bash
CHATGLANCE_BIN=$HOME/.chatarch/venv/bin/chatglance \
CHATGLANCE_RUNTIME_HOME=$HOME/.chatarch/glance \
bash <chatglance-repository>/scripts/refresh-projects-page.sh
```

By default the script uses the current runtime inventory JSON as `--baseline-data` before writing the next snapshot. This preserves reviewed categories only where current tree evidence does not contradict them and preserves valid reviewed Web metadata, while updating repo counts, PR/Issue counts, PyPI versions, entrypoints, actual CLI tree counts, and `generated_at`.

The script stages generated artifacts before touching the live files: it writes `chatarch-projects.json.next`, `projects-page.yml.next`, and `project-cli-tree-report.tsv.next`, builds `glance.yml.projects-candidate`, validates the candidate with the Glance binary, then backs up and replaces the live JSON, page YAML, CLI-tree report, and config together. A failed validation must not leave a new page YAML paired with old data/config.

The script writes:

```text
$CHATGLANCE_RUNTIME_HOME/data/chatarch-projects.json
$CHATGLANCE_RUNTIME_HOME/data/projects-page.yml
$CHATGLANCE_RUNTIME_HOME/data/project-cli-tree-report.tsv
$CHATGLANCE_RUNTIME_HOME/config/glance.yml.projects-candidate
```

It validates the candidate with:

```bash
$CHATGLANCE_RUNTIME_HOME/bin/glance -config $CHATGLANCE_RUNTIME_HOME/config/glance.yml.projects-candidate config:validate
```

If validation passes and the candidate differs, it backs up the live config, data, page YAML, and CLI-tree report, then replaces the live config/data/page/report artifacts. It intentionally does **not** restart or reload the Glance service; the operator or an outer wrapper owns service lifecycle.

## Required review before live

After every refresh, check:

1. `generated_at` is present and rendered as `刷新时间`.
2. `ChatGlance` appears in `repositories` and in the rendered page.
3. `counts.with_detected_version` is explainable under the PyPI-only rule.
4. `counts.with_detected_cli_entries` is entrypoint count, while `counts.with_actual_cli_tree` and `counts.with_actual_cli_business_commands` come from actual latest-PyPI CLI trees.
5. `counts.with_chatenv_dependency`, `counts.with_chatenv_entry_points`, and `counts.with_chatenv_fields` are explainable from default-branch package metadata, and sample detail popups render ENV descriptions without values.
6. `project-cli-tree-report.tsv` explains each Python package's entrypoint count, actual business command count, business command names, and resulting category.
7. `categories.python-early` / `Python (early)` did not disappear unexpectedly, and no complex CLI tree package remains early just because of stale baseline data.
8. Sample rows: `ChatCI` (trivial actual tree -> `Python (early)`), `ChatCRS` (complex actual tree -> `Python 包`), `ChatGlance`, `ChatSMTP`, `ChatSync`, `ChatFlow`, `ChatExplore`.
9. Secret scan for token/auth/password/header patterns returns no hits in project JSON/page YAML/CLI-tree TSV.
10. Live page order remains `ChatArch` → `项目` → `服务器`.
11. Anonymous smoke shows only the static public home and projected public project page; its JSON/YAML/HTML contains no private repository name, URL, description, CLI/ENV metadata, count, source metadata, or visibility label. Authenticated smoke retains the full page with literal `Public`/`Private` badges and `Unknown` for malformed visibility.
