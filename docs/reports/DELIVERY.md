# NOESIS M1–M5 交付总览

2026-10-26。分支 `codex/m1-public-foundation`。每个阶段均在验证后独立提交并推送。

| 阶段 | 提交 | 报告 |
|---|---|---|
| M1.0 公共层 | 2c6b738 | [M1.0](M1.0.md) |
| 审查 skill / 连续执行约定 | 995a723 | [Skill](review-skill.md) |
| M1.1 Claude Code | cf0eb33 | [M1.1](M1.1.md) |
| M1.2 Codex / 回填 | 44cce4f | [M1.2](M1.2.md) |
| M2 Git / 项目统一 | 6cdd526 | [M2](M2.md) |
| M3 浏览历史 | 83e283f | [M3](M3.md) |
| M4 收藏 / OCR | 196e97e | [M4](M4.md) |
| M5 日志 / 定时任务 / 审计 | 本报告所在提交 | [M5](M5.md) |

最终测试：119 项通过，包含原生 Vision OCR；真机脱敏审计 0 命中。
最近 7 天 Markdown 已生成，两个 launchd 任务已安装；应用代码未启用网络或 AI 提炼。

全局审查 skill 位于 `~/.codex/skills/post-code-review/SKILL.md`，仓库 AGENTS.md 要求写完代码、提交前执行。
重复实现、重复函数和无依据的防御直接精简；bug 按位置、影响、证据和修复状态记录在各阶段报告。

人工剩余事项：

1. 给 Safari 对应的真实 Python / 启动应用授权完全磁盘访问权限。
2. 安装 Hammerspoon，授权辅助功能、屏幕录制、浏览器自动化与 Apple 事件 JavaScript，重载配置。
3. 用 Obsidian 打开 `~/NOESIS`，执行 M4 交互清单，并在隔夜 / 睡眠唤醒后查看日志。

这些权限和真实 UI 验收没有被当作自动通过。Safari 当前失败已隔离，不阻止其他来源和每日日志。
M6 AI 提炼和 M7 前端不属于本次交付范围。
