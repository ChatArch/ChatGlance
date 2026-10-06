# 手动刷新

页面上的“手动刷新”按钮仅在已登录会话中通过现有 `/_chatglance/reset-policy/pages/` 控制服务工作；项目页访客看不到按钮。点击后仅刷新当前页（项目或服务器），不扫描账号、兑换卡片或更改定时计划。按钮立即显示进行中，随后显示忙碌、成功、部分成功或失败及真实快照采集时间；成功或部分成功会重新加载所属页面以更新卡片，且不会再次提交刷新。页面访问和取消不会发起刷新。定时任务占用共享刷新锁时，页面会报告忙碌而不会将其误报为成功。服务器备注编辑按既有配置别名和版本检查写入 runtime 私有目录；保存仅重绘旧服务器快照并更新卡片，不发起 SSH 探测。留空备注即清除显示内容。无 JavaScript 时写操作按钮不会提交。

`chatglance refresh` 是安装包自带的真实刷新入口，不依赖源码 checkout 或仓库脚本。

## 常用命令

| 目标 | 命令 |
|---|---|
| 全部已配置生成页 | `chatglance refresh` |
| 订阅与重置日历 | `chatglance refresh account-limits` |
| 网站服务卡片及监控快照 | `chatglance refresh sites` |
| 项目与服务器 | `chatglance refresh projects servers` |
| 只更新文件，不重启服务 | `chatglance refresh --no-restart` |
| 自动化读取结果 | `chatglance refresh --json-output` |
| 查看运行流水 | `chatglance runtime history list` |
| 预览/执行轮转 | `chatglance runtime history prune` / `... --apply` |

默认实例目录是有效 ChatArch home 下的 `glance/`，可以指定 `--runtime-home <runtime-home>`。
需要已有的 `config/glance.yml` 和 `bin/glance`；也可用 `--glance-bin <executable>` 指定校验程序。命令不会自动安装服务器或重新初始化账号。

## 配置来源

- `projects`：复用 `data/chatarch-projects.json` 中的 owner；缺省为 ChatArch。人工分类优先读取 `config/project-category-overrides.json`，否则使用旧快照。GitHub 凭据沿用既有 ChatGH/ChatEnv 机制。
- `servers`：读取 `config/server-inventory.yml`，只探测明确配置的服务器，不自动扩大扫描范围。
- `sites`：读取 `config/site-services.yml`；同一 ChatArch home 下存在 `uptime-gatus/data/gatus.db` 时读取现有监控结果，不发现新网站。
- `account-limits`：显式 `--profiles "work personal"` 优先，其次为 ChatEnv/process env 的 `CHATGLANCE_ACCOUNT_LIMITS_PROFILES`，最后复用当前快照的账号列表。没有账号配置时报错，不猜测账号。

默认项目刷新只查询元数据，不安装项目包。仅对相同发行版本、包名和命令入口复用已有 CLI 树证据；版本变化后不借用旧树。需要重新核验发行包时显式使用 `--actual-cli-tree`，该选项会通过既有 uvx 采集流程运行发行包 CLI。

## 失败、缓存与服务生命周期

- 与定时刷新及 `runtime maintain` 共用非阻塞锁 `logs/refresh-live-pages.lock`；已有刷新在执行时明确报错，不启动第二个发布者。
- 每页独立采集；失败页不覆盖原文件，其他成功页继续。官方日历的缓存规则见[重置策略](codex-reset-policy.md)。
- 先生成候选配置并执行真实 `glance config:validate`，通过后才备份和替换相关产物。校验失败不改线上文件；发布阶段失败会恢复已替换文件。
- 保留原页面顺序、账号配置和非生成内容；检测到校验期间有人改动配置则中止，避免覆盖。
- 同址可选登录配置的项目刷新由 config 中的 `public: true` 与 `authenticated-columns` 配对识别；重新生成匿名 allowlist 与已登录完整列，不把 full inventory 覆写到访客列。缺失配对时拒绝部分模式；`runtime maintain`、`projects update-config` 采用同一生成边界。
- 只有文件变化时才最多重启一次既有 Glance 用户服务；默认名称 `chatarch-glance.service`，可用 `--service-name` 指定。`--no-restart` 交给外层管理生命周期。
- 所有页面新鲜成功时返回 0；部分失败或缓存降级返回 1，同时输出实际结果。`--json-output` 的 `run_id`、`source`、`ok`、`pages`、`changed`、`published`、`restarted` 和 `backup_dir` 可供自动化读取。
- 服务器出现在线→不可达变化时，手动、定时和浏览器刷新发布真实离线状态；可选显式 `server_id`（缺省时由 alias 与受审 target/user/port 派生）及连接身份完全匹配时，原卡片保留并标旧最后成功硬件值，同时以可读、带时区的独立行显示最后成功与本次尝试时间。从未成功或身份变化时明确显示无历史数据。原生 CLI 仅需旧式整页阻止时使用 `--no-allow-offline-regression`。
- 每次 manual/scheduled/browser 尝试（含 busy、全失败、校验/发布/重启错误）写入 `private/refresh-history`。记录只含 allowlist 元数据；不保存异常原文、stdout/stderr、配置或账号快照。typed 默认保留 30 天、总量 256 MiB，并自动清理确认归属且未受保护的旧 bundle；CLI `prune` 默认只预览。
- 手动刷新始终按只读监控方式调用订阅采集，**不会兑换重置卡，也不会修改既有自动重置策略**。自动用卡不另设重置调度：它只在`--scheduled`的同一次订阅刷新中，使用刚读取的数据完成判断并最多消费一次。

## Python 接口与脚本

```python
from chatglance.refresh import refresh_runtime

result = refresh_runtime(pages=["sites", "account-limits"], restart=False)
assert result["reset_execution"] is False
assert result["run_id"]
```

只读/轮转 API 为 `chatglance.refresh_history.list_refresh_runs`、
`show_refresh_run`、`prune_refresh_history`。逐服务器缓存准备 API 为
`chatglance.server_cache.prepare_server_refresh`；它只返回待事务发布的
plan，不单独提交 last-good。完整 schema、legacy bootstrap 和保护规则见
[刷新历史与 last-good](refresh-history.md)。

可选脚本 `scripts/refresh-manual.sh` 只把参数转交给公开 CLI。部署专属的代理环境和账号配置保留在 runtime/ChatEnv，不写进通用脚本或仓库。定时器的原策略不因增加手动入口而改变。
