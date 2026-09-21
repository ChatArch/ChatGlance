# Codex reset policy


## Codex 重置卡与自动扫描

订阅详情按账号显示可用卡数、最近到期和最近动作。卡片中的“自动用卡设置”打开独立账号小窗，只有一个自动用卡开关；未知卡数不显示成0，没有立即兑换按钮。

兼容默认规则是：主额度窗口已用量 **至少95%**、距下一次自然重置 **超过24小时**、可用卡数 **大于0**。每个 profile 独立配置，缺省关闭；没有额外的全局开关。额外模型限额不触发。

推荐显式指定目标总额度窗口，例如 `target_window_seconds=604800` 表示 7 天窗口，既可位于 primary，也可位于 secondary；缺少该窗口时不回退到 5 小时窗口。账号主卡使用同一目标窗口展示。`min_remaining_seconds=129600` 表示自然重置剩余时间必须 **严格超过36小时**；等于36小时也不兑换。

可选 `skip_if_forecast_24h_above=70` 表示：公共来源的 **未来滚动24小时预测概率 >70%** 时不兑换；等于70%仍需满足全部其他条件。概率不是经过验证的准确率，也不等于北京时间下一自然日的概率。来源为独立、实验性的 codexreset.org；站点所示48小时事件命中率/召回率不用于此判断。

启用预测保护后，缺失、格式变化、未来时间戳或超过2小时的来源数据均阻止兑换。新鲜度取来源 snapshot 的更新时间，不以抓取时间或每分钟检查时间代替。只静态读取当前 forecast 的24小时值，不执行网页脚本，不取动画初始值、基准分数、历史预测或48小时API值。采集在账号决策前获取一次有大小/时间限制的公共响应，POST前再次检查所有保护；历史事件缓存仍仅用于展示。

```bash
chatglance account-limits collect --profiles "work personal" --output account-limits.json --no-execute-resets
chatglance account-limits render-page --data account-limits.json --output account-limits-page.yml
```

后端设置可来自进程环境或ChatEnv的ChatGlance schema，明确CLI值优先：

```dotenv
CHATGLANCE_ACCOUNT_LIMITS_RESET_POLICIES={"work":{"enabled":false,"threshold_percent":95,"min_remaining_seconds":129600,"target_window_seconds":604800,"skip_if_forecast_24h_above":70},"personal":{"enabled":false}}
CHATGLANCE_ACCOUNT_LIMITS_RESET_BASE_URL=https://gpt-relay.example.com/backend-api
```

某账号的`enabled=true`即允许该账号在全部条件满足时自动用卡，不影响其他账号。只读检查传`--no-execute-resets`；不带`--scheduled`的`chatglance refresh`也不消费。显式计划运行保留原每账号策略。旧全局字段须先迁移，见[重置控制](reset-controls.md)。reset base是可选的显式覆盖；不设置时继承Codex profile的backend base，usage始终保留该profile的base。ChatCRS禁用环境/系统Proxy，不启用本机代理或静默改走官方地址。

定期采集在同一次`--scheduled`调用中通过GET获取数据、评估条件，并且仅当全部条件满足时才POST兑换；没有独立的动态重置计时器。ChatGlance请求ChatCRS按标准ChatEnv流程保证access token有效，轮换值仅写入运行态token store；不在页面包内实现OAuth。续期被拒绝时显示凭据配置或续期失败，需要重新授权。缺字段、失败或陈旧数据不触发用卡；小窗只展示上一次计划刷新时各条件的通过/未通过及时间，不会在打开时重判。相同账号及别名共享持久化去重记录，位于ChatArch home下的`chatglance/`；先落盘请求ID再POST，一轮至多一张，超时/结果不明停止自动重试并显示“结果未确认，已阻止重复用卡”。只有明确reset结果且GET读回卡数下降、用量恢复才报成功。用卡会改变自然重置日期，不会购买Credits。

Python接口：`chatglance.codex_collector.collect_account_limits`、`chatglance.codex_resets.scan_profile`、`ResetPolicy`。发布包拥有采集逻辑，定时器直接调用`chatglance refresh --scheduled`，不依赖外部业务脚本。

## CRS 服务托管模式（0.1.13）

该模式需要 CRS 服务提供原生 Codex 管理接口，以及 ChatCRS 0.3.5 或更新的兼容客户端（提供 `CrsManagedCodexClient`）；0.3.4 不包含此接口。选择模式不会自动部署服务或升级客户端。

在 ChatGlance typed profile 或进程环境显式配置以下非敏感值：

```dotenv
CHATGLANCE_ACCOUNT_LIMITS_CRS_PROFILE=glance-service
CHATGLANCE_ACCOUNT_LIMITS_CRS_ACCOUNTS={"work":"00000000-0000-4000-8000-000000000001","personal":"00000000-0000-4000-8000-000000000002"}
CHATGLANCE_ACCOUNT_LIMITS_PROFILES="work personal"
```

`glance-service` 选择 ChatCRS 所属的 CRS 配置，只配置服务地址和专用管理 Key；不是本地 Codex OAuth profile。Glance 强制要求该 Key，不读取 Admin 会话、不回退用户名/密码；缺失、失效或越权直接失败。`work`、`personal` 是现有显示/策略标签，映射到固定 CRS 账号 ID，而不是模型自动调度池。所有选中标签都必须有映射。账号 ID 须为1至128个 ASCII 字符，首字符为字母或数字，其余仅允许字母、数字、`_`、`.`、`:`、`-`；不自动修剪或规范化。整份映射的重复键、缺失标签和非法 ID 会在公共预测读取、任何账号请求或消费前统一拒绝，不能先执行前面的合法账号。

此时额度、卡片和消费请求全部交给 CRS 原生管理 API；`CHATGLANCE_ACCOUNT_LIMITS_RESET_BASE_URL` 不参与该模式，不能把调用改回上游反代。页面行使用 `token_service=CRS`；缺少客户端、服务接口或有效管理鉴权时明确失败，绝不回退到页面机的 Codex ENV/token store。CRS profile 为空时仍使用原有本地 Codex 模式。

手动 `chatglance refresh account-limits` 保持不消费；计划运行继续遵守同一账号开关、额度/时间/预测条件和幂等守护，不新增全局开关。历史值仍只用于显示，不能授权用卡。迁移前应核对旧模式的未决消费记录，并先完成只读验证；不会自动迁移或清除旧台账，也不能把旧缓存当成新 CRS 账号的实时数据。

## 官方重置日历缓存

官方重置日历只展示公共来源确认的历史事件，不把账号预计重置窗口采样当作官方重置。
采集时传入 `--history` 指向上次快照；内置 `chatglance refresh` 会自动传入该路径。

```bash
chatglance account-limits collect --profiles "work personal" --history account-limits.json --output account-limits.next.json --no-execute-resets
```

来源请求失败或解析为空时，保留上次成功的事件、月份和日期高亮，并显示“更新失败，显示缓存”和最后成功时间。
连续失败不会把缓存时间改成本次刷新时间。恢复成功后使用新记录并清除缓存提示。
如果没有有效历史快照，则显示官方记录暂不可用；显式 `--no-public-reset` 不会重新启用旧记录。
同一天多次重置计入多次事件，但只高亮对应的一个日期格。该缓存仅影响展示，不参与重置卡消费决策。
