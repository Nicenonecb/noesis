# M5：定时任务预留目录

M0 不创建或加载 plist。M5 再生成含实际绝对解释器路径的
`com.justin.aibrain.collect.plist` 和 `com.justin.aibrain.daily.plist`。
按用户计划，分别每 1800 秒采集、23:30 采集并渲染。

需在 M5 明确：23:30 当日日志与“次日生成昨天完整日志”的差异，
补齐最后半小时及睡眠期间的漏跑，并验证日志轮转与时区。
