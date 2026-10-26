# NOESIS launchd 集成

`scripts/install.sh` 按当前项目和数据目录生成 plist 到 `~/Library/LaunchAgents/`。

| Label | 触发 | 命令 |
|---|---|---|
| com.justin.noesis.collect | 每 1800 秒，RunAtLoad | collect |
| com.justin.noesis.daily | 系统时区每天 23:30 | daily-run --catch-up 7 |

ProgramArguments 使用虚拟环境可执行文件的绝对路径，包含明确的数据目录；不依赖交互 shell。
PATH、标准输出和错误日志路径由安装器生成。daily-run 在部分来源失败时仍生成日志，保留退出码 1 供 doctor 诊断。

查看状态使用 `noesis doctor`。卸载使用 `scripts/uninstall.sh`，不会删除 NOESIS 数据。
