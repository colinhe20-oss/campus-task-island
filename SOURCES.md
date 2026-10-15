# 提取来源

本骨架依据 E:\mini-openclaw 的现有代码裁剪和改写，来源为浙江大学 Group10 的 mini-OpenClaw 教学项目。
团队上游：https://github.com/Zearth123/ZJU--mini_openclaw-group10

| 原代码 | 本骨架 | 处理 |
|---|---|---|
| agent/loop.py | agent/loop.py | 保留模型调用、工具分派、observation 回填、轮数上限、取消、事件；移除活动策划、Todo、输出路由和压缩耦合 |
| tools/base.py | tools/base.py | 沿用 Tool / ToolRegistry；增加参数校验和工具确认标记 |
| tools/fs.py、tools/more_tools.py | tools/fs.py | 提取 read/write/edit/glob/grep，绑定工作目录，去掉 artifact 路由和 rg 依赖 |
| tools/shell.py | tools/shell.py | 重写为 Windows / Linux 可选工具，不复制 bwrap 降级逻辑 |
| backend/client.py | backend/client.py | 保留协议转换，支持通用配置，增加 close，保留无效 JSON 供主循环反馈 |
| backend/fake_backend.py | backend/fake_backend.py | 换为确定性脚本后端，离线覆盖多轮工具调用 |
| agent/context.py | agent/context.py | 仅保留工具输出截断 |

原项目包含 Zearth / Zearth123、Colin He / colinhe20-oss、FY、通用作者名 root 及教学 starter 的贡献；具体个人分工见原仓库 CONTRIBUTORS.md。本次提取不将团队代码标为独立原创，不补写未经授权的项目许可证。没有复制第三方 gzh-design、其他 Skills 或 MCP 实现。

campus/ 业务模块、tools/campus.py 查询工具、tests/test_campus.py 和 examples/campus_demo.py 是在提取骨架后的新增实现，不是原项目已有的校园任务功能。
