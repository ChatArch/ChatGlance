<div align="center">
    <a href="https://pypi.python.org/pypi/ChatGlance">
        <img src="https://img.shields.io/pypi/v/ChatGlance.svg" alt="PyPI version" />
    </a>
    <a href="https://github.com/ChatArch/ChatGlance/actions/workflows/ci.yml">
        <img src="https://github.com/ChatArch/ChatGlance/actions/workflows/ci.yml/badge.svg" alt="Tests" />
    </a>
</div>

<div align="center">

[English](README.en.md) | [简体中文](README.md)
</div>

# ChatGlance

`ChatGlance` 是 ChatArch/WZHECNU Glance 网站部署相关源码与运维记录的 private repo。它沉淀当前站点的页面生成逻辑、配置转换规则、user-level service 模板、验收记录和安全边界；`chatglance` CLI 只是辅助执行这些记录和规则的管理入口。

它不是 NPM 项目，也不是重新实现 Glance 后端：上游 Glance 仍然是 Go 单二进制 dashboard server；`ChatGlance` 负责把 ChatArch 项目清单、Glance YAML 页面、inline HTML 表格、user-level systemd 单元和部署记录组织成可复用、可审查的源码与文档。

## Repo 内容

- `src/chatglance/`：项目页、服务器页、网站服务卡片页生成，Glance YAML patch、runtime maintenance、user-level systemd unit 渲染/安装等辅助代码。
- `tests/`：项目页、Disk root-only patch、runtime/systemd、workflow contract 的回归测试。
- `docs/quickstart.md`：新机器快速开始：以 Glance 前端配置为主、`chatglance` CLI 管理为辅的配置路径。
- `docs/cli-tree.md`：由真实 Click registry 生成并由测试锁定的完整/简洁 CLI 树与副作用边界。
- `docs/site-architecture.md`：ChatGlance 作为 Python 包、Glance runtime、生成配置和 runtime 数据脚本之间的边界。
- `docs/projects.md`：`项目` 页展示内容、PyPI-only 版本规则、entrypoint-only 展示规则、actual CLI tree 分类证据和刷新验收清单。
- `docs/infra.md`：Infra/`服务器` 页的配置机制、外部数据生成链路、刷新方式和 cron/timer 模板。
- `docs/deployment/current-site.md`：当前线上 Glance 网站的私有部署记录，包括服务拓扑、路径、user service/timer、local/public entry、验收和安全边界。
- `examples/server-inventory.example.yml` / `examples/site-services.example.yml`：可提交的脱敏 inventory 配置示例；真实 inventory 放在 runtime config 目录。
- `scripts/refresh-projects-page.sh`：刷新 GitHub/ChatGH 当前项目数据、生成 `项目` 页并安全替换 candidate config 的脚本模板。
- `scripts/refresh-server-status.sh` / `scripts/refresh-sites-page.sh`：可手动运行或挂 cron/systemd timer 的外部刷新脚本模板。
- `README.md` / `README.en.md` / `CHANGELOG.md`：对外/协作入口；避免写入 live auth、token、password hash 或代理凭据。

## 当前能力

- 通过 ChatGH/GitHub 当前数据刷新 repository inventory JSON，生成带 `generated_at` 的 Glance `项目` page；版本展示只看 PyPI，CLI 主表只展示 package entrypoint，Python early/non-early 分类使用 latest PyPI actual CLI tree/help 证据校正，旧 baseline 只保留为 reviewed audit evidence。
- `项目` 页一览表为每个仓库生成原生点击 `详情` 按钮；详情卡片展示项目 description、基础信息、CLI entrypoint、保留 `# comment` 的 brief CLI tree 代码块，以及真实注册的 ChatEnv Env key、说明、敏感标记和默认存在标记；有 ENV 元数据时 CLI/ENV 可点击切换，但不展示任何值。
- 当前 page tabs 固定为：`最近提交`、`待处理 PR / Issue`、`分类`、`一览表`。
- `待处理 PR / Issue` 只显示 PR/Issue 非 0 的仓库，并按 `(PR, Issue, 最近提交)` 降序。
- 生成 config 副本时清理 legacy generated pages：`Projects`、`ChatArch Projects`、`ChatArch Projects List`。
- 为 Glance `server-stats` 写入“只显示有意义磁盘”的 Disk 配置：当前 live 策略始终保留 `/`，只有当 `/home` 是独立挂载点时才加 `/home`；每个可见 mountpoint 都显式写入 `hide: false`，避免 Disk 显示 `n/a`，同时继续隐藏 snap/loop/tmp/overlay。
- 从 Infra inventory YAML 选择 SSH alias，执行只读采集，生成静态 `server-status.json`，再渲染 Glance `服务器`/Infra page。
- `服务器` 页的收起卡片显示 IP/CPU/内存/硬盘/状态；GPU、挂载目录、filtered `lsblk`、安全 `getdevices` 摘要、`Last Reboot` 放在展开详情中。
- 从 reviewed `site-services.yml` 生成 `网站服务` 页卡片：每个服务一张封面图、简介、健康状态、Uptime 详情和 public 跳转按钮；local host 只用于探测/运维配置，不展示在人类页面里。
- 维护 durable runtime：一次性 `runtime maintain` 可原子更新 live config、备份、校验；服务生命周期动作不放在默认 docs 示例里。
- 渲染并安装 user-level systemd units：主服务仍直接启动 upstream Glance Go binary；维护任务是独立 oneshot/timer，不是 Python wrapper。
- 通过 CLI 安装、启用、启动和回读当前 Glance 页面对应的 user service/timer。

## 快速开始

新机器配置类似当前站点时，先看 [`docs/quickstart.md`](docs/quickstart.md)：它把 `glance.yml` / widgets / HTML/CSS 作为主要前端配置入口，`chatglance` 只负责采集、渲染、校验、备份和替换这些管理动作。

```bash
pip install -e ".[dev]"
chatglance --help
chatglance --version
chatglance --tree
chatglance --tree-brief
python -m pytest -q
python -m build
python -m twine check dist/*
```

## CLI 树

完整命令面见 [`docs/cli-tree.md`](docs/cli-tree.md)。`chatglance --tree` 由 ChatStyle 从真实 Click registry 生成带参数签名的完整树；`chatglance --tree-brief` 保留相同节点和说明但省略签名。源码测试会直接运行两个入口，并与文档中的树逐字对齐。

刷新 `项目` 页的推荐入口同样是仓库脚本；它用 ChatGH 当前 repo 列表刷新 PR/Issue/时间字段，只读读取默认分支 manifest/entrypoint 证据，并从 PyPI 读取版本。默认用当前 runtime JSON 作为 baseline 保留人工 review 过的分类证据，同时优先用 latest PyPI `--tree-brief`（回退到 `--tree`/help）结果校正 Python 包成熟度；脚本会生成 `project-cli-tree-report.tsv` 作为审计报告。private repo 内容读取按显式 token 环境变量、当前 checkout 的 repo-local GitHub credential、ChatGlance typed ChatEnv active profile、ChatGH shared ChatEnv profile 的顺序回退，并且不打印 token。详细验收见 [`docs/projects.md`](docs/projects.md)：

```bash
CHATGLANCE_BIN=~/.chatarch/venv/bin/chatglance \
CHATGH_BIN=~/.chatarch/venv/bin/chatgh \
CHATGLANCE_RUNTIME_HOME=~/.chatarch/glance \
bash scripts/refresh-projects-page.sh
```

生成的项目页会在概览里显示 `刷新时间`，用于判断 PR/Issue 数据的新鲜度；一览表里的“详情”按钮会展示仓库基本信息、CLI entrypoint 和非密钥 ChatEnv/ENV schema metadata。

刷新 Infra/`服务器` 页的推荐入口是外部脚本，而不是手改 JSON：

```bash
cp examples/server-inventory.example.yml ~/.chatarch/glance/config/server-inventory.yml
$EDITOR ~/.chatarch/glance/config/server-inventory.yml

CHATGLANCE_BIN=~/.chatarch/venv/bin/chatglance \
CHATGLANCE_RUNTIME_HOME=~/.chatarch/glance \
CHATGLANCE_INFRA_CONFIG=~/.chatarch/glance/config/server-inventory.yml \
bash scripts/refresh-server-status.sh
```

脚本内部调用 `chatglance servers collect/render-page/update-config`，先生成 candidate config 并执行 `glance config:validate`，验证通过且内容变化时才备份 live config、替换；service manager 动作留给外层 cron/systemd wrapper 或人工操作。完整机制见 [`docs/infra.md`](docs/infra.md)。

刷新 `网站服务` 页使用固定 reviewed inventory，不自动扫描 Nginx。封面图可以由 `chatglance sites export-covers` 生成 SVG 并上传到 Share/其它图床，然后把 `cover_url` 写进 runtime inventory；没有 `cover_url` 时页面会使用内联 SVG 兜底：

```bash
cp examples/site-services.example.yml ~/.chatarch/glance/config/site-services.yml
$EDITOR ~/.chatarch/glance/config/site-services.yml

CHATGLANCE_BIN=~/.chatarch/venv/bin/chatglance \
CHATGLANCE_RUNTIME_HOME=~/.chatarch/glance \
CHATGLANCE_SITES_CONFIG=~/.chatarch/glance/config/site-services.yml \
bash scripts/refresh-sites-page.sh
```

## CLI 示例

刷新 GitHub/ChatGH 当前项目数据：

```bash
chatglance projects collect \
  --owner ChatArch \
  --chatgh-bin ~/.chatarch/venv/bin/chatgh \
  --output ~/.chatarch/glance/data/chatarch-projects.json
```

只生成 `项目` page YAML：

```bash
chatglance projects render-page \
  --data /path/to/chatarch-projects.json \
  --output playground/projects-page.yml
```

把生成页写入一个 Glance config 副本：

```bash
chatglance projects update-config \
  --data /path/to/chatarch-projects.json \
  --config /path/to/glance.yml \
  --output playground/glance.with-projects.yml
```

把 `server-stats` Disk 改成只显示 root 分区，写入 config 副本：

```bash
chatglance disks root-only \
  --config /path/to/glance.yml \
  --output playground/glance.root-disk.yml
```

查看 Infra 配置选中的服务器 aliases：

```bash
chatglance servers candidates \
  --inventory-config ~/.chatarch/glance/config/server-inventory.yml
```

手动刷新 Infra 静态数据和页面 YAML：

```bash
chatglance servers collect \
  --inventory-config ~/.chatarch/glance/config/server-inventory.yml \
  --output ~/.chatarch/glance/data/server-status.json

chatglance servers render-page \
  --inventory-config ~/.chatarch/glance/config/server-inventory.yml \
  --data ~/.chatarch/glance/data/server-status.json \
  --output ~/.chatarch/glance/data/server-page.yml

chatglance servers update-config \
  --inventory-config ~/.chatarch/glance/config/server-inventory.yml \
  --data ~/.chatarch/glance/data/server-status.json \
  --config ~/.chatarch/glance/config/glance.yml \
  --output ~/.chatarch/glance/config/glance.yml.infra-candidate
```

生成网站服务数据、封面图和页面 YAML：

```bash
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
```

维护一个 durable Glance runtime（默认 `~/.chatarch/glance`）：

```bash
chatglance runtime maintain \
  --runtime-home ~/.chatarch/glance
```

生成推荐 systemd user units：

```bash
chatglance runtime render-systemd \
  --runtime-home ~/.chatarch/glance \
  --chatglance-bin ~/.chatarch/venv/bin/chatglance \
  --output-dir playground/systemd
```

安装并启用 user-level systemd units（写入 `~/.config/systemd/user`，不需要 sudo）：

```bash
chatglance runtime install-systemd \
  --runtime-home ~/.chatarch/glance \
  --chatglance-bin ~/.chatarch/venv/bin/chatglance \
  --start
```

启动/回读当前页面对应的 user service/timer：

```bash
chatglance runtime start
chatglance runtime status
```

## 运行态边界

推荐拓扑是 **systemd 直接运行 Glance，chatglance 只做维护**：

- 主服务：`chatarch-glance.service` 直接执行 `~/.chatarch/glance/bin/glance -config ~/.chatarch/glance/config/glance.yml`。
- 可复用源码、脚本、文档都放在 ChatArch/ChatGlance repo 内，例如 `src/chatglance/`、`scripts/`、`docs/`、`examples/`。
- 内容数据：repository inventory JSON、缓存和生成快照放在 ChatArch-owned runtime：`~/.chatarch/glance/data/` 或 `~/.chatarch/glance/cache/`。
- Infra/site inventory：真实 `server-inventory.yml` 和 `site-services.yml` 是 runtime config；生成的 `chatarch-projects.json`、`projects-page.yml`、`server-status.json`、`server-page.yml`、`site-services.json`、`site-services-page.yml` 是 runtime 静态快照，不是源码。
- live config：`~/.chatarch/glance/config/glance.yml`；更新前写备份到 `~/.chatarch/glance/config/backups/`。
- 维护：`chatglance runtime maintain` 是 oneshot，可由 `chatarch-glance-maintenance.timer` 周期触发。
- 安装/启动：`chatglance runtime install-systemd --start` 与 `chatglance runtime start` 只使用 user-level systemd，不写 `/etc/systemd`。
- 不建议加 Python 长驻 wrapper：wrapper 会把 server 生命周期和内容生成耦合，反而不利于服务日志、健康检查和回滚。

## 安全边界

- CLI 默认写 output file，不默认覆盖 live `glance.yml`。
- 不保存或输出 Glance auth、password hash、GitHub token、proxy credential。
- live runtime、logs、backups、全量实时 JSON 快照默认不进源码仓库。
- 后续如需动态表格、搜索、中英文切换，再考虑增加小型静态前端层；当前 Python CLI 是基础层。
