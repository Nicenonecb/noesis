# 写后代码审查约定

日期：2026-10-26。用户已要求连续完成 M1.1–M5，逐阶段验证、提交；取代原计划阶段间等待确认的约定。

全局 skill：`~/.codex/skills/post-code-review/SKILL.md`，允许隐式调用。
仓库 `AGENTS.md` 在写完代码和提交前明确触发，审查结果写进对应阶段报告。
重复实现、重复函数和无依据的防御逻辑直接精简；bug 列出位置、触发条件、影响、证据和状态。
本任务实现造成的验收问题在原开发范围内修复；既有无关 bug 不自动改变行为。

本次仅新增执行约定，无运行时代码变更。原计划保存在 `docs/M1-M5_PLAN.md` 供后续核对。
M1.0 已推送到 `origin/codex/m1-public-foundation`。

验证：通过 skill-creator 的 quick_validate（使用本机离线缓存的 PyYAML）；完整 pytest 90 项通过。
