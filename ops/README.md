# ops/ —— 运维工具箱

日常维护用的四个工具，都是命令行程序（在仓库根目录跑，前缀 `.venv/Scripts/python.exe`）。

| 文件 | 白话 | 用法 |
| --- | --- | --- |
| doctor.py | 体检仪：一条命令查全系统健康（依赖/账套配置/跑批灯色/端口/升级面） | `.venv/Scripts/python.exe ops/doctor.py` |
| launcher.py | 启动器源码（启动明账.exe 的本体）：自动装环境→演示数据→首跑→开门户 | 双击仓库根的 启动明账.exe 即可 |
| backup.py | 备份本体：全账套金库+配置+密钥，例行与升级快照共用 | 双击仓库根的 备份数据.bat |
| upgrade.py | 升级协议引擎：14 个子命令覆盖 升级全流程（详见 UPGRADE.md 与手册 R-14） | `.venv/Scripts/python.exe ops/upgrade.py status` |
| upgrade_common.py | 上面三个共用的零件：版本读取、依赖指纹、布局通道探测 | （不直接跑） |

`launcher.ico` 是启动器图标素材；改 launcher.py 后要重新打包 exe（命令在该文件头部注释）。
