# NOESIS launchd 集成

`scripts/install.sh` 按当前项目和数据目录生成 plist 到 `~/Library/LaunchAgents/`。

| Label | 触发 | 命令 |
|---|---|---|
| com.justin.noesis.collect | 每 1800 秒，RunAtLoad | collect |
| com.justin.noesis.daily | 系统时区每天 23:30 | daily-run --catch-up 7 |

启用 `[digest] enabled = true` 时，daily 改为 00:30 执行 morning-run，另每 300 秒检查补生成/重试，RunAtLoad。
同时安装 com.justin.noesis.morning：原生本地窗口进程，在解锁/登录后请求展示；每天确认展示一次。
三个任务的时间门限、缓存与展示确认由程序负责，00:30 不主动弹窗。

ProgramArguments 使用实际 Python 二进制和 `~/NOESIS/bin/noesis.pyz`，包含明确的数据目录；不依赖桌面 checkout 或交互 shell。
PATH、标准输出和错误日志路径由安装器生成。daily-run 在部分来源失败时仍生成日志，保留退出码 1 供 doctor 诊断。

查看状态使用 `noesis doctor`。卸载使用 `scripts/uninstall.sh`，不会删除 NOESIS 数据。
