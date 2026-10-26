# NOESIS 开发约定

每次写完代码、提交前，读取并执行 `~/.codex/skills/post-code-review/SKILL.md`。
审查覆盖本阶段全部差异；在 `docs/reports/` 的对应阶段报告记录精简、bug 清单和验证结果。

按里程碑独立提交，提交前运行完整 pytest。M1.1–M5 已交付，用户已授权继续 M6：
DeepSeek 晨报、00:30 总结及解锁展示。网络调用限定在 digest/client.py 的官方 API；
其他采集与渲染保持本地。Key 使用 DEEPSEEK_API_KEY 环境变量或数据目录 .env（0600），
按用户要求不依赖钥匙串。日志仅记录状态、计数与用量，凭证文件留在仓库外。

本仓库的子任务和审查在主线程顺序完成。真实对话、浏览内容、截图和凭证不得写入报告或 fixture。
