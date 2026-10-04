# 架构与能力边界

ChatGlance 是 Python 包与 CLI，Glance 是读取 YAML 并处理认证/页面/API 的 Go 服务。两者不共享 Python 会话，也不增加第二个公开站点。

```text
审核后的清单 / 运行时快照
        │  ChatGlance 的显式采集、投影、渲染
        ▼
候选 glance.yml / 页面片段 ── Glance config:validate ──► 运维决定发布
                                              │
                           Glance 的现有 auth、路由、缓存与服务端选列
```

## 功能分区

| 分区 | ChatGlance 负责 | Glance / 运维负责 |
|---|---|---|
| 项目 | GitHub 元数据、公开 allowlist、分类/版本、只存结构信息的 CLI/Env 描述 | 身份判定、同一 `/项目` 选择认证列、阻止私有内容接口泄露 |
| 服务器 | 仅指定别名的只读状态快照、`server-stats` 磁盘呈现 | SSH 凭据与可见权限、部署及运行状态 |
| 网站服务 | 审核清单、SVG 封面、可选监控状态 | URL 可用性、资产服务与外部网络权限 |
| 订阅 | 已脱敏的额度/重置日历，人工开关与计划判断 | 原有账号认证、逐账号策略及有权限的消费操作 |

## 同址依赖不可替代

官方 Glance v0.8.5 **不提供** `public: true` 与 `authenticated-columns` 配对功能。维护版 [ChatArch/glance chatarch-v0.1.0](https://github.com/ChatArch/glance/releases/tag/chatarch-v0.1.0) 已提供这两项能力与 Linux amd64 资产。部署前校验 `SHA256SUMS`，通过 `config:validate`，并执行浏览器/API 双身份回读；Python 包与 Glance 服务端二进制分别安装和验收。

私有的 Glance YAML 可能含 `auth`，完整 inventory 可含 Private 仓库；它们属于运行时输入，不能提交到源码、文档站、公开 assets、错误消息或公开响应。共享 head、branding、assets 必须单独审计。离线 detached public 候选命令继续存在，但不等同于同域会话选择。详细边界见 [项目与访问](projects.md)。

## 文档与发布是不同流水线

源码测试、已安装 wheel 的 CLI 检查、MkDocs 严格构建、PR `/dev/` 预览和 main 根站更新是分开的证据。文档站不接受凭据或个人运行时信息；后续仍须验证 Pages 源分支、About 链接、预览评论 URL 及最终域名外部可访问性。包标签/PyPI 和实际 Glance 服务升级由发布者另行控制。
