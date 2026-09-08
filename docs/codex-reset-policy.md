# Codex reset policy


## Codex 重置卡与自动扫描

订阅详情按账号显示可用卡数、最近到期时间、策略和最近动作。页面只展示，无阈值设置或消费按钮；未知卡数不会显示成0。

默认规则是：主额度窗口已用量 **至少95%**、距下一次自然重置 **超过24小时**、可用卡数 **大于0**，三项同时满足才可用卡。primary/secondary按实际时间判断，不假设哪个是周窗口；额外模型限额不触发。每个profile独立配置，缺省关闭；实际消费还需显式执行开关。

```bash
chatglance account-limits collect --profiles "work personal" --output account-limits.json --no-execute-resets
chatglance account-limits render-page --data account-limits.json --output account-limits-page.yml
```

后端设置可来自进程环境或ChatEnv的ChatGlance schema，明确CLI值优先：

```dotenv
CHATGLANCE_ACCOUNT_LIMITS_RESET_POLICIES={"work":{"enabled":true,"threshold_percent":95,"min_remaining_seconds":86400},"personal":{"enabled":false}}
CHATGLANCE_ACCOUNT_LIMITS_RESET_BASE_URL=https://chatgpt.com/backend-api
CHATGLANCE_ACCOUNT_LIMITS_RESET_EXECUTE=false
```

只有审核后才能将执行开关设为true或传`--execute-resets`。只读验收传`--no-execute-resets`，覆盖已有配置。reset base是可选的显式覆盖，只用于重置卡接口，usage保留Codex profile的base；网络/代理由部署环境提供。

定期采集只GET，不发quota模型探测，不隐式刷新OAuth；过期凭据显示失败，由原有凭据维护流程处理。缺字段、失败或陈旧数据不触发用卡，旧值仅作展示。相同账号及别名共享持久化去重记录，位于ChatArch home下的`chatglance/`；先落盘请求ID再POST，一轮至多一张，超时/结果不明停止自动重试并显示待核对。只有明确reset结果且GET读回卡数下降、用量恢复才报成功。用卡会改变自然重置日期，不会购买Credits。

Python接口：`chatglance.codex_collector.collect_account_limits`、`chatglance.codex_resets.scan_profile`、`ResetPolicy`。发布包拥有采集逻辑，旧脚本仅为薄入口。
