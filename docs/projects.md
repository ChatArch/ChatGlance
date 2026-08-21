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
3. **待处理 PR / Issue**
   - only repositories with open PRs or open issues.
4. **分类**
   - reviewed project categories, including the short label `Python (early)` for early Python packages;
   - group titles include repository counts, for example `Python 包 (31)`;
   - category group order is `Python 包`, `Node / npm 包`, service/docs/other projects, then `Python (early)`;
   - Python package early/non-early classification is checked against the latest published package's actual CLI tree, not just entrypoint count or stale overrides.
5. **一览表**
   - repository link and a native-click detail button;
   - open PR count;
   - open issue count;
   - version;
   - type/category;
   - ChatEnv/ENV summary badge only when schema metadata or `chatenv.configs` registration exists;
   - package CLI entrypoint;
   - actual CLI tree business-command evidence in the generated JSON/TSV review artifact;
   - docs link candidate;
   - latest commit date;
   - table category order is `Python 包` first, `Node / npm 包` next, then service/docs/other projects, with `Python (early)` projects last.
6. **仓库详情卡片**
   - GitHub/docs links, description, version/category/PR/Issue/commit metrics;
   - package CLI entrypoints plus a scrollable brief CLI tree code block when actual tree evidence is available;
   - ChatEnv schema table when a provider/schema is registered: schema, ENV key, description, sensitivity flag, and default-presence flag only;
   - dependency-only ChatEnv projects are omitted from the ENV detail section until they register a provider/schema.

## Refresh rules

- `ChatGlance` must appear on the project page when it is visible in the ChatArch repository list.
- Version display is **PyPI-only**. Do not use GitHub tags, GitHub releases, `pyproject.toml`, `package.json`, or local manifests as version sources for the page.
- CLI display in the table remains **entrypoint-only**. For Python packages this means `project.scripts` / `project.gui-scripts`; for Node packages this means `package.json` `bin` entries. Do not expand Click/Typer/npm subcommands into the compact table cell.
- Python package classification uses actual CLI tree evidence when available: the refresh installs the latest PyPI package with `uvx --from <package>@latest <entrypoint> --tree-brief` first, falls back to `--tree`/`--help`, and counts non-option business command nodes. `--help`, `--version`, `--tree`, and `--tree-brief` are global options, not business commands.
- `Python (early)` is for placeholder/scaffold/trivial packages: no business subcommands in the actual CLI tree, or explicit placeholder/scaffold/PyPI-name-registration evidence. A package with real business subcommands is `Python 包` even if an older baseline/override marked it as early.
- `--baseline-data` may preserve reviewed categories for projects without stronger current tree evidence, but stale early overrides must not demote complex CLI packages such as ChatCRS.
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
CHATGH_BIN=$HOME/.chatarch/venv/bin/chatgh \
CHATGLANCE_RUNTIME_HOME=$HOME/.chatarch/glance \
bash /home/zhihong/Playground/core/ChatGlance/scripts/refresh-projects-page.sh
```

By default the script uses the current runtime inventory JSON as `--baseline-data` before writing the next snapshot. This preserves reviewed categories only where current tree evidence does not contradict them, while updating repo counts, PR/Issue counts, PyPI versions, entrypoints, actual CLI tree counts, and `generated_at`.

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
11. Public unauthenticated smoke still redirects to `/login`.
