# 项目页与同址可选登录

项目页的全量 inventory 是**服务端私有输入**。只有源行的 `private` 值是字面布尔 `false` 才能投影为访客项目；`true` 和缺失/畸形都不能进入访客视图。公开仓库的 URL 也要经过允许字段和外部 HTTPS 校验，不能仅按 CSS/JS 隐藏私有行。

## 同一页面的两个服务端布局

维护版 [ChatArch/glance chatarch-v0.1.0](https://github.com/ChatArch/glance/releases/tag/chatarch-v0.1.0) 提供 `public: true` 与 `authenticated-columns`：有效会话时服务端以认证列**替换**普通 `columns`。访客只读普通列；其它页面默认仍需认证。官方 Glance v0.8.5 无此能力；从维护版发布页下载 Linux amd64 资产并用附带的 `SHA256SUMS` 校验，不能只升级 Python 包。

| 同一 `/项目` 页面 | 访客 `columns` | 有效会话 `authenticated-columns` |
|---|---|---|
| 仓库 | 仅 literal `private: false` | 全部 Public/Private/Unknown |
| 信息 | 从 allowlist 重新计算统计/分类，无私有 CLI、Env 或计数 | 全量细节、CLI/Env 的**结构描述**及可见性标记 |
| 路由 | 原 `项目` 名称与 `/项目` slug | 同一 slug，不再开第二公开站点 |

首页同样有访客的固定书签列和原有私有首页的认证列；服务器、网站服务、订阅等页面不能因为入口公开而放宽。访客导航不包含这些页面，直访和内容接口要由 Glance 验证会话。`auth` 与受信的 `server` 路由不变；共享 `document.head`、`head-widgets` 和可访问的私有资产不被悄悄复制：不安全时直接拒绝候选。读者需在实际部署时核验缓存的 `no-store` / `Vary: Cookie` 及注销后的行为。

## 候选与后续刷新

```bash
chatglance access render-single-origin-optional-login \
  --config private.yml --inventory inventory.json --output candidate.yml
glance -config candidate.yml config:validate
```

以上需在隔离目录对合成数据运行，且 `glance` 应是具备上述能力的已核对二进制。候选私有文件以 `0600` 写入，不输出 `auth`；不触发服务切换。`projects update-config`、`runtime maintain`、`refresh projects` 根据配置中**受信**的成对页面字段重新生成访客与认证列，不能将清单中不可信的 audience 标志当权限开关；不完整模式拒绝。旧普通私有配置仍按原默认逻辑渲染。

历史 `access render-public` 仍可用于**离线**审查独立候选，不能将其当作同一网址可选登录的部署步骤。项目表还按最近提交、PR/Issue、分类展示；Python 包成熟度基于已发布版本的实际 CLI 树，而非仅根据 entrypoint 数量；候选链接、ChatEnv 字段说明都不能成为公布凭据的途径。进一步的行为验证见 [运行验收](operations.md)。
