# 刷新、运行与验收

**区分三个边界：**本地生成候选、在已有 runtime 发布经校验的快照、启动或重启实际 Glance 服务。前两项不能证明外部网址已更新。

## 手动读取与明确计划

```bash
chatglance refresh projects --no-restart
chatglance refresh sites --no-restart
chatglance refresh --json-output --no-restart
```

`refresh` 只对已有 Glance 配置中的受管页面采集并发布快照，按页返回成功/部分失败。候选先用指定 Glance binary 的 `config:validate` 校验，再备份并替换；失败页保留旧文件，运行中使用共享非阻塞锁。`--no-restart` 保留运行进程不变。上例只是**示意**：缺 runtime、凭据或校验程序时命令会失败，绝不自动构建环境。

无 `--scheduled` 的手动调用不兑换重置卡；订阅页面只是展示当前快照。定时刷新应仍在既有调度链中显式使用 `--scheduled` 和逐账号策略，不能通过阅读按钮状态代替授权。刷新项目若识别到同址可选登录模式，访客列会重新从 Public allowlist 生成，认证列保留全量视图；不匹配布局会拒绝而非覆写私有行。

## 手动检查并用卡

登录后打开订阅详情中的账号控制小窗，点击 **检查并用卡**。接受二次确认后，服务端重新读取该账号的当前策略、真实额度和可用卡；达到配置阈值且其余时间窗、预测、账号及幂等条件全部满足，才尝试使用至多一张明确的卡。它不必等待下一次定时扫描，也不会降低现有保护条件。

取消确认、查看页面、普通刷新和未运行 JavaScript 的原生表单都不会兑换。结果显示为成功、条件未满足或结果待确认，并标注本次检查时间；上方执行清单仍明确标识为上次计划检查的快照。结果待确认时不要重复操作，应先核实账本和额度。生产验收只查看或取消确认；消费路径用合成账号和卡片验证。

## 服务边界

- `projects update-config` 写**显式输出路径**，不是直接部署；同址候选输出不能别名覆盖输入。
- `runtime maintain` 会维护现有运行配置并可选择验证、备份或重启；在真实环境调用前必须确认输入、权限和备份目录。
- `runtime render-systemd` 可审查模板；`runtime install-systemd` 和 `runtime start` 会更改 user-level service/timer。本站文档**不会**启动它们。
- 服务器采集只读取明确列出的 SSH 别名；网站服务清单由运维审定，不自动扫描域名。`server-stats` 只显示有意义的磁盘挂载点。

## 部署后的阅读与安全验收

1. 在目标**同一网址**匿名读公开首页和 `/项目`，检查导航、内容接口、HTML/JSON/缓存均没有 Private 标识、URL、计数或 CLI/Env。
2. 用现有 Glance 账号登录，读同一路径确认全量 Public/Private/Unknown；直访未授权页面和内容接口应受服务器保护。
3. 注销并刷新、返回和再次读取，确认私有响应不能从缓存复现；移动/桌面导航均须手工检查。
4. 确认实际 Glance 可执行文件具有 `public`、`authenticated-columns` 能力，并保留升级前配置与回滚方案。**不要**把静态文档站构建成功当作这些结果。

页面发布另有 [GitHub Actions](https://github.com/ChatArch/ChatGlance/actions) 流程；PR 预览目标 `/dev/`，main 根站发布。两者都需在真实 Pages 配置和外部域名读回后才能宣称上线。
