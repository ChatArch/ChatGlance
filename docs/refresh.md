# 手动刷新

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
- 只有文件变化时才最多重启一次既有 Glance 用户服务；默认名称 `chatarch-glance.service`，可用 `--service-name` 指定。`--no-restart` 交给外层管理生命周期。
- 所有页面新鲜成功时返回 0；部分失败或缓存降级返回 1，同时输出实际结果。`--json-output` 的 `ok`、`pages`、`changed`、`restarted` 和 `backup_dir` 可供自动化读取。
- 服务器出现在线→不可达变化时，手动刷新默认保留旧快照并报告失败；确认要发布当前离线状态时使用 `--allow-offline-regression`。
- 手动刷新始终按只读监控方式调用订阅采集，**不会兑换重置卡，也不会修改既有自动重置策略**。既有自动执行调度与这个手动入口分开。

## Python 接口与脚本

```python
from chatglance.refresh import refresh_runtime

result = refresh_runtime(pages=["sites", "account-limits"], restart=False)
assert result["reset_execution"] is False
```

可选脚本 `scripts/refresh-manual.sh` 只把参数转交给公开 CLI。部署专属的代理环境和账号配置保留在 runtime/ChatEnv，不写进通用脚本或仓库。定时器的原策略不因增加手动入口而改变。
