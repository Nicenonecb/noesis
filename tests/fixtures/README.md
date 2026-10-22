# 合成样本

这些文件从零编造。所有项目、ID、路径、消息、URL 和凭据均为测试数据。
`.invalid` 是保留的无效域名，不发网络请求。

- `claude_code.jsonl`：字符串/text、工具结果、isMeta、sidechain、thinking、工具调用、外围请求缓存。
- `codex_current.jsonl`：本机观测到的 response_item、item_completed 两种消息通道和注入包装。
- `codex_history.jsonl`：独立历史格式，提供与会话样本的重复消息。
- `codex_legacy_candidate.jsonl`：未在本机见到的兼容候选；不是实测证据。
- `malformed_tail.jsonl`：完整坏行、未知类型、末尾无换行的半条记录；故意不是完整 JSONL。
- `chrome.sql`：本机实测列名，全部数据自行构造；包括同时间不同 visit 和黑名单 URL。
- `arc_unverified.sql`、`safari_unverified.sql`：未验证的最小假定 schema。

SQL 只在测试的临时目录建库；不提交二进制数据库。解析器与去重测试将在 M1/M3 补齐。
