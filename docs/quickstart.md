# 新机器快速开始：配置一个可定制的 Glance 站点

这个页面面向“我要在一台新机器上配置一个类似当前 ChatArch Glance 网站，但以后还会继续定制前端”的场景。

核心原则：**Glance 前端配置是主角，`chatglance` CLI 只是管理助手**。

- 你主要维护的是 `glance.yml`、页面顺序、widgets、inline HTML/CSS、静态 JSON 数据和渲染出来的 page YAML。
- `chatglance` 只负责把可重复的步骤工具化：采集只读数据、生成页面片段、生成 candidate config、校验、备份、替换。
- 可复用源码、脚本和文档都在 ChatArch/ChatGlance repo 内；生成静态快照只放 ChatArch-owned runtime 或当前 ChatArch workspace project 的 `playground/`。
- 真实账号、密码、cookie、SSH 私钥、完整 SSH config、代理凭据和 live backup 不进仓库。

## 0. 目录约定

推荐每台机器使用一个独立 runtime home：

```text
~/.chatarch/glance/
  bin/glance                         # upstream Glance Go binary
  config/glance.yml                  # live Glance config，前端配置主入口
  config/server-inventory.yml        # Infra/服务器页 inventory，runtime config
  config/site-services.yml           # 网站服务页 reviewed inventory，runtime config
  config/backups/                    # 替换前备份
  data/chatarch-projects.json        # 生成的项目页仓库清单快照
  data/projects-page.yml             # 生成的项目页 Glance YAML
  data/project-cli-tree-report.tsv   # 生成的 Python CLI tree 分类审计 TSV
  data/server-status.json            # 生成的服务器状态快照
  data/server-page.yml               # 生成的服务器页 Glance YAML
  data/site-services.json            # 生成的网站服务卡片快照
  data/site-services-page.yml        # 生成的网站服务页 Glance YAML
  cache/                             # 其它可再生成缓存
  logs/                              # 外层调度器日志
```

源码仓库只放 ChatArch/ChatGlance 可复用内容，不放 live 静态快照或凭据：

```text
docs/quickstart.md                   # 本页面
docs/infra.md                        # Infra 刷新机制细节
examples/server-inventory.example.yml
examples/site-services.example.yml
scripts/refresh-projects-page.sh
scripts/refresh-server-status.sh
scripts/refresh-sites-page.sh
src/chatglance/
```

## 1. 安装最小工具

在控制机上安装 ChatGlance CLI。开发/源码 checkout 场景：

```bash
cd /path/to/ChatGlance
python3 -m pip install -e ".[dev]"
chatglance --version
chatglance --tree
```

已有发布包时也可以用普通安装方式：

```bash
python3 -m pip install ChatGlance
chatglance --version
```

> CLI 不是站点后端。真正对外服务仍由 upstream Glance binary 读取 `glance.yml` 后提供。

## 2. 准备 Glance 前端配置

新机器上最先要有一个能工作的 `glance.yml`。可以从已有站点脱敏复制，也可以从 upstream Glance 示例开始。

最小结构示意：

```yaml
pages:
  - name: ChatArch
    slug: home
    columns:
      - size: full
        widgets:
          - type: html
            source: |
              <section class="cg-hero">
                <h1>ChatArch</h1>
                <p>自定义入口。</p>
              </section>

  - name: 项目
    slug: projects
    columns:
      - size: full
        widgets:
          - type: html
            source: |
              <p>项目页稍后由 chatglance projects render-page 生成。</p>

  - name: 服务器
    slug: servers
    columns:
      - size: full
        widgets:
          - type: html
            source: |
              <p>服务器页稍后由 chatglance servers render-page 生成。</p>
```

你以后想定制视觉效果时，优先改这些地方：

- page 顺序和 `name` / `slug`
- Glance widget 类型和布局
- `html` widget 里的 HTML/CSS
- `项目` 页的数据来源和表格文案
- `服务器` 页卡片文案、展开字段、颜色和分组
- `网站服务` 页卡片文案、封面图、public 跳转和 Uptime 状态入口

CLI 应该只是帮你把这些片段稳定生成出来，而不是把前端自由度锁死。

## 3. 配置 Infra inventory

从示例复制一份 runtime config：

```bash
mkdir -p ~/.chatarch/glance/config ~/.chatarch/glance/data ~/.chatarch/glance/config/backups
cp examples/server-inventory.example.yml ~/.chatarch/glance/config/server-inventory.yml
$EDITOR ~/.chatarch/glance/config/server-inventory.yml
```

推荐使用显式 `hosts`，不要长期依赖自动扫描：

```yaml
page:
  name: "服务器"
  slug: "servers"
  widget_title: "服务器状态"

inventory:
  default_candidates: false
  exclude: []
  hosts:
    - alias: "infra-cube-1"
      label: "cube-1"
      group: "cube"
      connection_kind: "内网连接"
    - alias: "infra-public-1"
      label: "public-1"
      group: "public"
      connection_kind: "公网连接"

collection:
  timeout: 18
  workers: 8
```

字段边界：

- `alias` 是控制机本地 SSH config 里的别名。
- `label` / `display_name` 只影响前端显示。
- `group` 只影响展示分组/排序语义。
- `connection_kind` 是展示文案，不应该携带凭据。
- `exclude` 用来排除 laptop、local test、退役机器或重复 alias。
- 真实 SSH config 不提交到仓库。

## 4. 先预览再更新

项目页先刷新当前 GitHub/ChatGH 数据。这个命令会更新 PR/Issue/时间字段，并只读读取默认分支的 `pyproject.toml`、`package.json` 和入口声明；它不会 clone、build 或执行各仓库源码。为了判断 Python 包是否已经具备真实业务 CLI，它会默认用 `uvx --from <package>@latest <entrypoint> --tree` 安装并探测 latest PyPI 包的 CLI tree，必要时 fallback 到 help 输出。private repo 内容读取优先使用 `CHATGLANCE_GITHUB_TOKEN` / `GITHUB_TOKEN` / `GH_TOKEN`，否则复用当前 ChatGlance checkout 里 `chatgh set-token` 配好的 repo-local GitHub credential，不打印 token：

```bash
chatglance projects collect \
  --owner ChatArch \
  --chatgh-bin ~/.chatarch/venv/bin/chatgh \
  --output ~/.chatarch/glance/data/chatarch-projects.json
```

生成项目页 YAML：

```bash
chatglance projects render-page \
  --data ~/.chatarch/glance/data/chatarch-projects.json \
  --output ~/.chatarch/glance/data/projects-page.yml
```

把项目页写入 candidate config：

```bash
chatglance projects update-config \
  --data ~/.chatarch/glance/data/chatarch-projects.json \
  --config ~/.chatarch/glance/config/glance.yml \
  --output ~/.chatarch/glance/config/glance.yml.projects-candidate
```

项目页概览会显示 `刷新时间`，用于判断 PR/Issue 等 GitHub 数据是什么时间刷新的。

服务器页先看 inventory 选中了哪些机器：

```bash
chatglance servers candidates \
  --inventory-config ~/.chatarch/glance/config/server-inventory.yml
```

生成只读状态快照：

```bash
chatglance servers collect \
  --inventory-config ~/.chatarch/glance/config/server-inventory.yml \
  --output ~/.chatarch/glance/data/server-status.json
```

生成服务器页 YAML：

```bash
chatglance servers render-page \
  --inventory-config ~/.chatarch/glance/config/server-inventory.yml \
  --data ~/.chatarch/glance/data/server-status.json \
  --output ~/.chatarch/glance/data/server-page.yml
```

把页面写入 candidate config：

```bash
chatglance servers update-config \
  --inventory-config ~/.chatarch/glance/config/server-inventory.yml \
  --data ~/.chatarch/glance/data/server-status.json \
  --config ~/.chatarch/glance/config/glance.yml \
  --output ~/.chatarch/glance/config/glance.yml.infra-candidate
```

用 Glance 自己的校验确认 candidate 可用：

```bash
~/.chatarch/glance/bin/glance -config ~/.chatarch/glance/config/glance.yml.infra-candidate config:validate
```

网站服务页从固定 reviewed inventory 渲染，不自动扫描 Nginx。local host 只用于 Gatus/local vhost 探测，不展示到前端页面；人类入口只显示 public 跳转：

```bash
cp examples/site-services.example.yml ~/.chatarch/glance/config/site-services.yml
$EDITOR ~/.chatarch/glance/config/site-services.yml

chatglance sites collect \
  --inventory-config ~/.chatarch/glance/config/site-services.yml \
  --gatus-db ~/.chatarch/uptime-gatus/data/gatus.db \
  --output ~/.chatarch/glance/data/site-services.json

chatglance sites export-covers \
  --data ~/.chatarch/glance/data/site-services.json \
  --output-dir playground/site-covers \
  --public-base-url https://share.public.wzhecnu.cn/chatglance-site-covers/ \
  --updated-data ~/.chatarch/glance/data/site-services.json

chatglance sites render-page \
  --data ~/.chatarch/glance/data/site-services.json \
  --output ~/.chatarch/glance/data/site-services-page.yml

chatglance sites update-config \
  --data ~/.chatarch/glance/data/site-services.json \
  --config ~/.chatarch/glance/config/glance.yml \
  --output ~/.chatarch/glance/config/glance.yml.sites-candidate

~/.chatarch/glance/bin/glance -config ~/.chatarch/glance/config/glance.yml.sites-candidate config:validate
```

如果 inventory 里已经写了 `cover_url`（例如 Share 图床 URL），页面直接使用该图片；否则会使用内联 SVG 兜底。

确认通过后，再把 candidate 提升为 live config，并保留备份：

```bash
cp ~/.chatarch/glance/config/glance.yml \
  ~/.chatarch/glance/config/backups/glance.$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S+0800).yml
mv ~/.chatarch/glance/config/glance.yml.infra-candidate \
  ~/.chatarch/glance/config/glance.yml
```

## 5. 一条命令刷新

熟悉之后，可以用仓库里的脚本模板把上面流程串起来。

刷新项目页：

```bash
CHATGLANCE_BIN=~/.chatarch/venv/bin/chatglance \
CHATGH_BIN=~/.chatarch/venv/bin/chatgh \
CHATGLANCE_RUNTIME_HOME=~/.chatarch/glance \
bash scripts/refresh-projects-page.sh
```

刷新服务器页：

```bash
CHATGLANCE_BIN=~/.chatarch/venv/bin/chatglance \
CHATGLANCE_RUNTIME_HOME=~/.chatarch/glance \
CHATGLANCE_INFRA_CONFIG=~/.chatarch/glance/config/server-inventory.yml \
bash scripts/refresh-server-status.sh
```

项目页脚本做的事：

1. `projects collect` 用 ChatGH 当前 repo 列表生成 `chatarch-projects.json`，并用 latest PyPI actual CLI tree/help 证据校正 Python early/non-early 分类。
2. 写出 `project-cli-tree-report.tsv`，记录 entrypoint 数、actual business command 数、命令名和分类结果，便于审计 `ChatCI` / `ChatCRS` 这类样本。
3. `projects render-page` 生成 `projects-page.yml`。
4. `projects update-config` 生成 `glance.yml.projects-candidate`。
5. 运行 `glance ... config:validate`。
6. 如果内容变化，备份旧 `glance.yml`、项目 JSON、项目 page YAML 和 CLI-tree TSV，再一起替换。
7. 输出 `changed=true/false`，给外层 cron、timer 或人工流程判断。

服务器页脚本做的事：

1. `collect` 生成 `server-status.json`。
2. `render-page` 生成 `server-page.yml`。
3. `update-config` 生成 `glance.yml.infra-candidate`。
4. 运行 `glance ... config:validate`。
5. 如果内容变化，备份旧 `glance.yml` 并替换。
6. 输出 `changed=true/false`，给外层 cron、timer 或人工流程判断。

脚本不保存凭据，也不直接管理服务生命周期。

## 6. 前端定制怎么保持灵活

建议把定制分成三层：

| 层级 | 主要改哪里 | 适合放什么 |
|---|---|---|
| Glance 原生配置 | `config/glance.yml` | 页面顺序、columns、widgets、主题、导航 |
| 生成页面片段 | `server-page.yml`、项目页 YAML | 表格、卡片、状态摘要、展开详情 |
| CLI 规则 | `src/chatglance/` | 可重复的数据采集、渲染、patch、校验逻辑 |

常见定制建议：

- 只是换标题、顺序、颜色、说明文案：优先改 `glance.yml` 或 HTML/CSS 模板。
- 要新增一个静态 tab：先手写 page YAML，稳定后再决定要不要加入 CLI 渲染器。
- 要把某个数据源变成长期自动更新：先定义 runtime config 和 generated JSON，再让 CLI 生成页面。
- 不要为了一个前端小改动先设计复杂后端服务；Glance 的优势就是静态配置 + 轻量刷新。

## 7. 项目页类型判断标准

`项目` 页来自 repository inventory JSON，但展示层会做一层轻量归一化，避免把内部长 key 直接暴露给前端。

当前约定：

- 成熟 Python 包：显示 `Python 包`。
- 早期 Python 包：显示 `Python (early)`。
- Node/npm 包：显示 `Node / npm 包`。
- 服务/应用：显示 `服务 / 应用`。
- 文档/站点：显示 `文档 / 站点`。

`Python (early)` 的判断标准：

1. actual CLI tree/help 里没有业务子命令，只有入口名或全局 option flags，例如 `--help`、`--version`、`--tree`。
2. 或者描述、baseline、manifest 等证据明确说明它是 placeholder、scaffold、PyPI name registration 之类早期包。
3. 旧 inventory 中的 `python-package-template/early`、`template/early` 或 `python-early` 可以作为 reviewed evidence 保留，但不能压过当前 actual CLI tree。

成熟 Python 包的优先信号：latest PyPI 包的 `<entrypoint> --tree` 或 help 输出里能看到面向业务对象/资源的实体子命令。这个信号会覆盖旧 inventory 里的 early/template 分类，避免 `ChatCRS` 这类已经成熟的包继续被旧快照误标。

这会把 `ChatFlow`、`ChatExplore`、`ChatSMTP`、`ChatSync` 这类 placeholder/entrypoint-only package 从普通 `Python 包` 校正到 `Python (early)`，同时让已有实体命令面的 `ChatCRS` 显示为 `Python 包`。

## 8. 新机器验收清单

- [ ] `glance.yml` 能通过 `glance ... config:validate`。
- [ ] 页面导航中能看到预期 tabs，例如 `ChatArch`、`项目`、`服务器`。
- [ ] `项目` 页数据由 `chatglance projects collect` 刷新，概览里能看到当前 `刷新时间`。
- [ ] `server-inventory.yml` 只包含要展示的 Infra aliases。
- [ ] `chatglance servers candidates --inventory-config ...` 输出符合预期。
- [ ] `server-status.json` 和 `server-page.yml` 是生成物，不手工长期维护。
- [ ] `服务器` 收起卡片只显示 IP / CPU / 内存 / 硬盘 / 状态。
- [ ] GPU、挂载目录、filtered devices、`Last Reboot` 在展开详情里。
- [ ] 所有时间字段显示北京时间 `+08:00`。
- [ ] 未登录访问仍按站点策略进入登录边界。
- [ ] 没有把 auth、token、cookie、SSH 私钥、代理凭据写入仓库或报告。

## 9. 下一步

- 机制细节：[`docs/infra.md`](infra.md)
- 脱敏 inventory 模板：[`examples/server-inventory.example.yml`](../examples/server-inventory.example.yml)
- 项目页刷新脚本：[`scripts/refresh-projects-page.sh`](../scripts/refresh-projects-page.sh)
- 服务器页刷新脚本：[`scripts/refresh-server-status.sh`](../scripts/refresh-server-status.sh)
