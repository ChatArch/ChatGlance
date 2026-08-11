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
   - refreshed data may preserve categories from a prior reviewed inventory via `--baseline-data`.
5. **一览表**
   - repository link;
   - open PR count;
   - open issue count;
   - version;
   - type/category;
   - package CLI entrypoint;
   - docs link candidate;
   - latest commit date.

## Refresh rules

- `ChatGlance` must appear on the project page when it is visible in the ChatArch repository list.
- Version display is **PyPI-only**. Do not use GitHub tags, GitHub releases, `pyproject.toml`, `package.json`, or local manifests as version sources for the page.
- CLI display is **entrypoint-only**. For Python packages this means `project.scripts` / `project.gui-scripts`; for Node packages this means `package.json` `bin` entries. Do not expand Click/Typer/npm subcommands into the project table.
- A refresh must not use CLI command surface to promote or demote reviewed project categories. Use `--baseline-data` to preserve reviewed classifications such as `Python (early)`.
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

By default the script uses the current runtime inventory JSON as `--baseline-data` before writing the next snapshot. This preserves reviewed categories while updating current repo counts, PR/Issue counts, PyPI versions, entrypoints, and `generated_at`.

The script stages generated artifacts before touching the live files: it writes `chatarch-projects.json.next` and `projects-page.yml.next`, builds `glance.yml.projects-candidate`, validates the candidate with the Glance binary, then backs up and replaces the live JSON, page YAML, and config together. A failed validation must not leave a new page YAML paired with old data/config.

The script writes:

```text
$CHATGLANCE_RUNTIME_HOME/data/chatarch-projects.json
$CHATGLANCE_RUNTIME_HOME/data/projects-page.yml
$CHATGLANCE_RUNTIME_HOME/config/glance.yml.projects-candidate
```

It validates the candidate with:

```bash
$CHATGLANCE_RUNTIME_HOME/bin/glance -config $CHATGLANCE_RUNTIME_HOME/config/glance.yml.projects-candidate config:validate
```

If validation passes and the candidate differs, it backs up the live config, data, and page YAML, then replaces the live config/data/page artifacts. It intentionally does **not** restart or reload the Glance service; the operator or an outer wrapper owns service lifecycle.

## Required review before live

After every refresh, check:

1. `generated_at` is present and rendered as `刷新时间`.
2. `ChatGlance` appears in `repositories` and in the rendered page.
3. `counts.with_detected_version` is explainable under the PyPI-only rule.
4. `counts.with_detected_cli_entries` is entrypoint count, not subcommand count.
5. `categories.python-early` / `Python (early)` did not disappear unexpectedly.
6. Sample rows: `ChatGlance`, `ChatCRS`, `ChatSMTP`, `ChatSync`, `ChatFlow`, `ChatExplore`.
7. Secret scan for token/auth/password/header patterns returns no hits in project JSON/page YAML.
8. Live page order remains `ChatArch` → `项目` → `服务器`.
9. Public unauthenticated smoke still redirects to `/login`.
