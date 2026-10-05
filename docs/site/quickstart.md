# 快速开始：先验证候选

## 可携带的本地起点（此功能尚未发布）

在安装含此功能的 wheel 后，运行 `chatglance runtime paths`、`chatglance runtime init`；审查 `config/glance.yml` 的 loopback 首页、空 inventory 与空快照。随后从可信 Go fork 工件执行 `chatglance runtime install-binary --archive reviewed.tar.gz --sha256 EXPECTED_64_HEX --binary-version chatarch-vX.Y.Z+40_LOWERCASE_HEX`（版本必须替换为实际精确输出），使用 `chatglance runtime render-portable --output-dir ./review-units` 仅生成待审单元。`runtime serve` 必须由运维显式运行；不自动安装/启动服务。源码、wheel、Go 二进制、运行配置数据、OS 入口是五层独立边界；fork 承担可选登录，原版不保证支持。完整配置与激活步骤见 [自包含运行](deployment.md)。

默认不联网、不采集、不开公网、不执行用卡。登录须先在 typed ChatEnv 提供 `CHATGLANCE_LOGIN_USER`、`CHATGLANCE_LOGIN_SECRET` 和 bcrypt `CHATGLANCE_LOGIN_PASSWORD_HASH`，再执行 `runtime init --with-auth`；YAML 只保存 Go `${ENV}` 引用，子进程环境优先采用进程值，再查 active ChatEnv。`CHATGLANCE_WEB_PORT`、可选的 `CHATGLANCE_PUBLIC_ORIGIN` / `CHATGLANCE_CONTROL_PORT`、项目 owner 与刷新频率/页面是非密钥设置。CRS 和 GitHub 保持共享 profile/resolver，不新建 token store；旧站迁移不导出密钥。仅显式 `render-portable --page projects` 等生成非账户定时任务；controls 需 `--controls` 且先配置登录和 HTTPS origin。示例反代保留登录及旧项目重定向；无自动发布或部署。

Glance 的 `glance.yml`、widgets 与 HTML/CSS 决定站点外观；ChatGlance 辅助生成页面、检验配置并维护快照。不要把示例配置当作生产部署脚本。

## 1. 在隔离环境安装并确认命令

当前源码 checkout 可用 `python -m pip install -e .` 安装；PyPI 安装 `python -m pip install ChatGlance` 需核对实际发布版本。**可选登录 CLI 需要包含该功能的 0.1.18 源码/发行包**，不是已发布 0.1.17 的行为。

```bash
chatglance --version
chatglance --tree-brief
chatglance access render-single-origin-optional-login --help
```

没有现成配置时，从 [Glance 的维护分支](https://github.com/ChatArch/glance) 查看支持的 Glance YAML 结构，准备一个**合成的** `private.yml` 和 `inventory.json`。保持账号与服务路由在原有配置里，不将真实文件提交到 Git。原版 v0.8.5 不能校验此可选登录配置。

## 2. 生成同址候选

在现存的非 symlink 私有目录中运行；下列文件名是占位符，命令不修改现有服务：

```bash
chatglance access render-single-origin-optional-login \
  --config private.yml \
  --inventory inventory.json \
  --output candidate.yml
```

输出只报告完成状态，不打印 `auth` 或私有行；目标需与输入不同，候选以 `0600` 原子写入。原有首页和其它需要登录的页面保持身份；项目页名称仍为“项目”，规范路径改为 `/projects`（旧 `/项目` 须由代理精确重定向）。其他页面不能因为新首页开放而改成访客可见。

## 3. 验证、审查，再由运维决定是否部署

对**明确选定且包含** `public` + `authenticated-columns` 能力的 Glance 可执行文件运行：

```bash
glance -config candidate.yml config:validate
```

检查匿名列只含 literal `private: false` 仓库；已登录列含全量行及 Public/Private/Unknown 标识。新站切换、账号会话、直访私有 API、登出缓存和移动导航的验证由部署方在隔离环境完成，生成候选不等于完成验收。详情见 [项目与访问](projects.md) 和 [刷新与运行](operations.md)。
