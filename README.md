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

文档站点（首次部署后可访问）：[ChatGlance 文档](https://arch.gh.wzhecnu.cn/ChatGlance/)。源码阶段请阅读 [站点首页](docs/site/index.md)；此链接尚不代表 Pages 已发布。

# ChatGlance

`ChatGlance` 是 ChatArch/WZHECNU Glance 网站部署相关源码与运维工具仓库。它沉淀当前站点的页面生成逻辑、配置转换规则、user-level service 模板、验收记录和安全边界；`chatglance` CLI 只是辅助执行这些记录和规则的管理入口。

它不是 NPM 项目，也不是重新实现 Glance 后端：上游 Glance 仍然是 Go 单二进制 dashboard server；`ChatGlance` 负责把 ChatArch 项目清单、Glance YAML 页面、inline HTML 表格、user-level systemd 单元和部署记录组织成可复用、可审查的源码与文档。

## 重置判据与人工开关

订阅卡片默认折叠重置卡信息，预测只在居中小窗中显示。每个账号只有一个“自动用卡”开关，并纳入同一执行清单与暂停/等待/就绪状态；继承网站字体和配色。开启须明确确认，不提供立即兑换按钮。部署与安全边界见 [重置控制](docs/reset-controls.md)。

## CRS 托管订阅（0.1.13）

可显式选择包含专用管理 Key 的 CRS 配置与固定账号映射，让订阅采集只调用 CRS 服务、上游 OAuth 留在服务端。该模式需要配套原生 CRS API 和 ChatCRS 0.3.5 或更新的兼容客户端；缺配置/能力/权限时不会回退到本地 OAuth，旧模式不被自动切换。手动刷新仍不消费。配置与迁移边界见 [Codex 重置策略](docs/codex-reset-policy.md)。

## Repo 内容

- `src/chatglance/`：项目页、服务器页、网站服务卡片页生成，Glance YAML patch、runtime maintenance、user-level systemd unit 渲染/安装等辅助代码。
- `tests/`：项目页、Disk root-only patch、runtime/systemd、workflow contract 的回归测试。
- `docs/quickstart.md`：新机器快速开始：以 Glance 前端配置为主、`chatglance` CLI 管理为辅的配置路径。
- `docs/cli-tree.md`：由真实 Click registry 生成并由测试锁定的完整/简洁 CLI 树与副作用边界。
- `docs/site-architecture.md`：ChatGlance 作为 Python 包、Glance runtime、生成配置和 runtime 数据脚本之间的边界。
- `docs/projects.md`：`项目` 页展示内容、PyPI-only 版本规则、entrypoint-only 展示规则、actual CLI tree 分类证据和刷新验收清单。
- `docs/infra.md`：Infra/`服务器` 页的配置机制、外部数据生成链路、刷新方式和 cron/timer 模板。
- `docs/deployment/current-site.md`：原生 CLI 与 user service/timer 的部署约定；具体拓扑、密钥和现场验收保留在外部运行态。
- `examples/server-inventory.example.yml` / `examples/site-services.example.yml`：可提交的脱敏 inventory 配置示例；真实 inventory 放在 runtime config 目录。
- `chatglance refresh [PAGES]...`：安装包内置的采集、候选校验与发布入口，不依赖源码 checkout 或机器本地业务脚本。
- `chatglance refresh --scheduled`：供现有 timer 调用的显式计划运行方式；保留每账号自动策略和统一锁。
- `README.md` / `README.en.md` / `CHANGELOG.md`：对外/协作入口；避免写入 live auth、token、password hash 或代理凭据。

## 当前能力

- 通过 ChatGH/GitHub 当前数据刷新 repository inventory JSON，生成带 `generated_at` 的 Glance `项目` page；版本展示只看 PyPI，CLI 主表只展示 package entrypoint，Python early/non-early 分类使用 latest PyPI actual CLI tree/help 证据校正，旧 baseline 只保留为 reviewed audit evidence。
- `项目` 页一览表为每个仓库生成原生点击 `详情` 按钮；详情卡片展示项目 description、基础信息、CLI entrypoint、保留 `# comment` 的 brief CLI tree 代码块，以及真实注册的 ChatEnv Env key、说明、敏感标记和默认存在标记；有 ENV 元数据时 CLI/ENV 可点击切换，但不展示任何值。
- 当前 page tabs 固定为：`最近提交`、`PR-issue`、`分类`、`一览表`。
- 支持显式 public/private 项目视图：authenticated 默认视图保留全量清单，只把字面 boolean 标记显示为 `Public`/`Private`，缺失或畸形值显示 `Unknown`；anonymous 渲染边界自行从 full inventory 投影，发布的 allowlist artifact 不包含 private 行、source/CLI/Env/evidence 元数据、private 派生计数或可见性标记。
- 同址可选登录候选：`chatglance access render-single-origin-optional-login --config PRIVATE.yml --inventory FULL.json --output CANDIDATE.yml`，单 Glance 实例同一 `/项目` slug 按会话选择公开/完整列；私有候选文件不可作为 guest asset 发布。详见 [项目与访问](docs/site/projects.md)。
- 同址可选登录需要 [ChatArch/glance chatarch-v0.1.0](https://github.com/ChatArch/glance/releases/tag/chatarch-v0.1.0) 的 `public` 与 `authenticated-columns` 能力；该发布提供 Linux amd64 二进制和 `SHA256SUMS`。原版 Glance v0.8.5 不支持这些字段。安装 ChatGlance 不会自动替换 Glance 二进制，升级前需校验 checksum、配置和双身份访问。
- `chatglance access render-public` 从显式 full config/inventory 生成 public YAML/JSON 候选；public config 只含静态公开首页和项目页，不继承 `auth`、private server、网站服务、订阅详情、服务器页或原首页 runtime widgets。repository/docs/Web 链接必须是外部 HTTPS URL；两个 mode-`0600` 候选在同一个预先存在的非 symlink 目录内 stage、fsync 并成对原子替换，第二个发布失败时回滚第一个。
- `PR-issue` 只显示 PR/Issue 非 0 的仓库，并按 `(PR, Issue, 最近提交)` 降序。
- 生成 config 副本时清理 legacy generated pages：`Projects`、`ChatArch Projects`、`ChatArch Projects List`。
- 为 Glance `server-stats` 写入“只显示有意义磁盘”的 Disk 配置：当前 live 策略始终保留 `/`，只有当 `/home` 是独立挂载点时才加 `/home`；每个可见 mountpoint 都显式写入 `hide: false`，避免 Disk 显示 `n/a`，同时继续隐藏 snap/loop/tmp/overlay。
- 从 Infra inventory YAML 选择 SSH alias，执行只读采集，生成静态 `server-status.json`，再渲染 Glance `服务器`/Infra page。
- `服务器` 页的收起卡片显示 IP/CPU/内存/硬盘/状态；GPU、挂载目录、filtered `lsblk`、安全 `getdevices` 摘要、`Last Reboot` 放在展开详情中。
- 从 reviewed `site-services.yml` 生成 `网站服务` 页卡片：每个服务一张封面图、简介、健康状态、Uptime 详情和 public 跳转按钮；local host 只用于探测/运维配置，不展示在人类页面里。
- 维护 durable runtime：一次性 `runtime maintain` 可原子更新 live config、备份、校验；服务生命周期动作不放在默认 docs 示例里。
- 渲染并安装 user-level systemd units：主服务仍直接启动 upstream Glance Go binary；维护任务是独立 oneshot/timer，不是 Python wrapper。
- 通过 CLI 安装、启用、启动和回读当前 Glance 页面对应的 user service/timer。

## 快速开始

新机器配置类似当前站点时，先看 [快速开始](docs/site/quickstart.md)：它把 `glance.yml` / widgets / HTML/CSS 作为主要前端配置入口，`chatglance` 只负责采集、渲染、校验、备份和替换这些管理动作。

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

## 手动刷新与 CLI 树

安装包即可刷新已有 runtime，不再要求进入源码目录运行脚本：

```bash
python -m pip install ChatGlance
chatglance refresh
chatglance refresh account-limits
chatglance refresh projects sites
```

- 不指定页面时，只刷新当前 Glance 配置里的生成页；支持 `projects`、`servers`、`sites`、`account-limits`。
- 默认运行目录为有效 ChatArch home 下的 `glance/`，可用 `--runtime-home` 指定已有实例。
- 使用已有 inventory、ChatEnv/当前快照中的账号列表和 GitHub 凭据。不会重新初始化服务、发现新网站或兑换重置卡。
- 手动刷新与定时器共享锁；先采集、生成候选并校验，再备份替换，保留原页面顺序和非生成内容；最多重启一次已有 Glance 用户服务。
- 失败页面保留原产物，成功页继续更新。部分失败/缓存降级返回非零退出码，不把旧值报告成新鲜成功。
- `--no-restart` 只更新产物；`--json-output` 输出机器可读结果。已在线服务器变为不可达默认不覆盖旧快照，确认要展示新离线状态时使用 `--allow-offline-regression`。
- 项目页默认复用**相同发行版本、包名和命令入口**的 CLI 树证据，避免每次手动刷新都安装所有包；`--actual-cli-tree` 才重新探测当前发行包。

手动与定时刷新都直接调用安装包 CLI。迁移后停用机器本地和源码目录下的旧业务脚本入口；外部仅保留 ChatEnv/密钥、inventory、数据与薄 systemd 配置。手动刷新不改变既有自动重置策略，也不消费卡片；CRS 托管模式由服务端续期上游 OAuth；旧本地 Codex 模式仍由 ChatCRS 的标准 ChatEnv 流程处理。

```bash
chatglance refresh --scheduled --runtime-home "$HOME/.chatarch/glance" --json-output
```

账号请求使用 profile 中的反向代理 Base URL，ChatCRS 忽略所有本地 Proxy；不在刷新命令前调用 `proxy_on`。可用 `--server-inventory`、`--sites-inventory`、`--gatus-db` 和其他采集参数显式选择非敏感配置。只读诊断不要传 `--scheduled`。

站点 [分段 CLI 索引](docs/site/cli.md) 按操作边界组织；需要完整注册树可见 [CLI 树](docs/cli-tree.md)，或运行 `chatglance --tree` / `chatglance --tree-brief`。

## CLI 示例

生成 detached public config/inventory 候选（只写显式输出，不发布或刷新）：

```bash
mkdir -p playground
chatglance access render-public \
  --config /path/to/full-glance.yml \
  --inventory /path/to/full-projects.json \
  --config-output playground/public-glance.yml \
  --inventory-output playground/public-projects.json
```

刷新 GitHub/ChatGH 当前项目数据：

```bash
chatglance projects collect \
  --owner ChatArch \
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


## 订阅页额度探测模型

`collect-codex-account-limits.py` 使用 ChatCRS Python API 探测 Codex Responses 额度响应头。可在采集进程环境或刷新 service 的 EnvironmentFile 中配置 `CHATGLANCE_ACCOUNT_LIMITS_MODELS`，值为 profile 名称到可用模型名称的 JSON 对象，例如 `{"example":"supported-codex-model"}`。刷新脚本会继承该变量。

仅精确匹配的 profile 覆盖额度探测模型；其他 profile、usage GET、凭据和账号名单不变。未设置、空白对象或空白模型值时保留 ChatCRS 默认模型；无效 JSON/非字符串模型返回采集错误。模型 404 不等于 token 失效，应先检查模型可用性，不要反复轮换凭据。


## Codex 重置卡与自动扫描

订阅详情按账号显示可用卡数、最近到期和最近动作。卡片中的“自动用卡设置”打开独立账号小窗，只有一个自动用卡开关；小窗展示上一次计划刷新的独立条件结果和时间，打开或刷新小窗不会重新判断、更不会立即兑换。

默认规则是：主额度窗口已用量 **至少95%**、距下一次自然重置 **超过24小时**、可用卡数 **大于0**，三项同时满足才可用卡。primary/secondary按实际时间判断，不假设哪个是周窗口；额外模型限额不触发。每个profile独立配置，缺省关闭；没有额外的全局开关。

```bash
chatglance account-limits collect --profiles "work personal" --output account-limits.json --no-execute-resets
chatglance account-limits render-page --data account-limits.json --output account-limits-page.yml
```

后端设置可来自进程环境或ChatEnv的ChatGlance schema，明确CLI值优先：

```dotenv
CHATGLANCE_ACCOUNT_LIMITS_RESET_POLICIES={"work":{"enabled":false,"threshold_percent":95,"min_remaining_seconds":86400},"personal":{"enabled":false}}
CHATGLANCE_ACCOUNT_LIMITS_RESET_BASE_URL=https://chatgpt.com/backend-api
```

某账号的`enabled=true`即允许该账号在全部条件满足时自动用卡，不影响其他账号。只读检查传`--no-execute-resets`；`chatglance refresh`也始终不消费。旧全局字段须先迁移，见[重置控制](docs/reset-controls.md)。reset base是可选的显式覆盖，只用于重置卡接口，usage保留Codex profile的base；网络/代理由部署环境提供。

每次计划刷新在同一轮内先GET读取额度、卡片和预测，再按该次新鲜数据判断；只有全部条件满足时才在该次刷新中POST兑换，绝不另起动态重置计时器。手动刷新和查看小窗都不消费。缺字段、失败或陈旧数据不触发用卡；页面保留上次计划检查的通过/未通过结果和时间。相同账号及别名共享持久化去重记录，位于ChatArch home下的`chatglance/`；先落盘请求ID再POST，一轮至多一张，结果不明停止自动重试并明确显示“结果未确认，已阻止重复用卡”。只有明确reset结果且GET读回卡数下降、用量恢复才报成功。用卡会改变自然重置日期，不会购买Credits。

Python接口：`chatglance.codex_collector.collect_account_limits`、`chatglance.codex_resets.scan_profile`、`ResetPolicy`。发布包拥有采集逻辑，旧脚本仅为薄入口。
