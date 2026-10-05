# 自包含运行（需人工审核）

适用于安装包含 portable 功能的 wheel；不代表已经发布 PyPI，也不自动迁移生产。支持 POSIX/Linux 用户级 systemd，Go 二进制须匹配审核的平台与架构。ChatArch/glance fork 维护可选登录/页面能力。五层是可分享源码、安装的 wheel、验证过的 Go 二进制、私有运行配置/快照、可选 OS/nginx 薄入口；安装后不依赖 checkout。

```text
<CHATARCH_HOME>/
  envs/                         typed ChatEnv profiles
  glance/
    bin/glance                  验证过的 Go fork，不从 PyPI 获得
    bin/glance.provenance.json  来源 tag/revision、实际 version 与双 SHA256
    config/glance.yml           默认 127.0.0.1:8080 空首页
    config/server-inventory.yml hosts: []，不自动 SSH
    config/site-services.yml    空网站清单
    config/reverse-proxy.example.conf  待审 nginx 配置
    data/                        空仓库/服务器/网站/账户快照
    scripts/{start,install,refresh}.sh  wheel 内薄 CLI 包装
    logs/  staging/              logs 下共享刷新锁
<review-dir>/chatglance-portable*.service|timer   尚未注册的候选单元
```

## 配置和验证

在隔离 Python 环境安装审核的 wheel；指定专用 `CHATARCH_HOME`（如 `$PWD/isolated-home`）。执行 `chatenv status`、`chatenv init -t chatglance -i`；用交互的 `chatenv set -i` 输入 `CHATGLANCE_LOGIN_USER`（支持 email）、`CHATGLANCE_LOGIN_SECRET`（Go 兼容标准 base64，**解码后恰好 64 bytes**）、bcrypt `CHATGLANCE_LOGIN_PASSWORD_HASH`，不要把密钥放进命令参数或脚本。`chatenv list` / `chatenv use -t chatglance PROFILE` 可激活已有 typed profile。无登录时省略 `--with-auth`；已有无登录配置不自动升级，迁移先用新运行目录生成候选。

```bash
chatglance runtime paths
chatglance runtime init --with-auth
chatglance runtime install-binary --archive reviewed.tar.gz --sha256 EXPECTED_SHA256 --binary-version chatarch-vX.Y.Z+40_LOWERCASE_HEX
chatglance runtime render-portable --page projects --interval 30min --output-dir ./review-units
```

将示意版本替换为可执行文件 `--version` 的**精确输出**（`chatarch-v主.次.修+40位小写哈希`）。本地 SHA256 已审核的 tar 仅含一个普通 `glance` 文件；安装器限时执行验证暂存文件的 `--version`，比较后记录归档/二进制 SHA256；错误不替换未知文件，不下载 latest。`chatglance refresh` 使用同一 typed 环境交给 Go `config:validate`；生产前另验真实 binary 和匿名/登录会话。初始配置只有时钟首页；先审查清单、配置所需页面再刷新，空 hosts 不会连接 SSH。旧 `runtime maintain` 可选，不强制维护 timer。

## 显式运行及激活边界

`chatglance runtime serve` 显式前台启动 Go，登录密钥只进入子进程环境：进程 env 优先，其次 active typed ChatEnv。`chatglance refresh projects --runtime-home DIR --service-name chatglance-portable.service` 用 native 共享锁校验并发布，**仅在内容改变时**重启指定自身服务。`render-portable` 不传页面/间隔时读取 typed `CHATGLANCE_REFRESH_PAGES`（空格/逗号分隔）及 `CHATGLANCE_REFRESH_INTERVAL`；默认不生成 timer。只允许 projects/servers/sites，不自动扫描账户或消费卡。`CHATGLANCE_PROJECTS_OWNER` 配置 owner，显式 `--projects-owner` / `--owner` 可覆盖。

需要 controls 时先启用 Go 登录及私有 `/account-limits` 页，再设置 HTTPS `CHATGLANCE_PUBLIC_ORIGIN` 和 `CHATGLANCE_CONTROL_PORT`（默认 5679），显式 `chatglance runtime render-portable --controls --output-dir ./review-units` 或 `chatglance runtime controls`。Controls 使用 Go 会话，凭据不全则拒绝。审核 `config/reverse-proxy.example.conf` 中同址 `/_chatglance/reset-policy/` 路由、登录 cookie 和旧 `/项目` 重定向；外网前配置真实 TLS/主机名，不自动安装/reload nginx。CRS 继续消费已有 profile、GitHub 继续共享 resolver，无新 token store。

**审核后才可**运行 `systemd-analyze --user verify ./review-units/*`，由运维手工复制候选到用户级 systemd 目录，再决定 `systemctl --user daemon-reload`、`enable`、`start`。`render-portable` 本身不注册/启动服务；旧 `runtime install-systemd` 是独立的状态变更入口，不是自动迁移。实际参数请运行 `chatglance --tree` 与 `chatglance --tree-brief` 核对；仓库根目录 `docs/cli-tree.md` 保存受测试约束的注释树。软件发布、生产升级与外部部署需另行授权。

审核通过后的**运维手动动作示例，不由 ChatGlance 执行**：

```bash
systemd-analyze --user verify ./review-units/*
mkdir -p "$HOME/.config/systemd/user"
install -m 0644 ./review-units/chatglance-portable.service "$HOME/.config/systemd/user/"
# 若明确配置 --page，再安装候选 refresh.service 和 refresh.timer
install -m 0644 ./review-units/chatglance-portable-refresh.service ./review-units/chatglance-portable-refresh.timer "$HOME/.config/systemd/user/"
# 若明确启用 --controls，再单独安装候选 controls.service
systemctl --user daemon-reload
systemctl --user enable --now chatglance-portable.service
systemctl --user enable --now chatglance-portable-refresh.timer
# 可选：systemctl --user enable --now chatglance-portable-controls.service
```
