# 快速开始：先验证候选

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

输出只报告完成状态，不打印 `auth` 或私有行；目标需与输入不同，候选以 `0600` 原子写入。原有首页、`/项目` 路径和其它需要登录的页面保持身份。其他页面不能因为新首页开放而改成访客可见。

## 3. 验证、审查，再由运维决定是否部署

对**明确选定且包含** `public` + `authenticated-columns` 能力的 Glance 可执行文件运行：

```bash
glance -config candidate.yml config:validate
```

检查匿名列只含 literal `private: false` 仓库；已登录列含全量行及 Public/Private/Unknown 标识。新站切换、账号会话、直访私有 API、登出缓存和移动导航的验证由部署方在隔离环境完成，生成候选不等于完成验收。详情见 [项目与访问](projects.md) 和 [刷新与运行](operations.md)。
