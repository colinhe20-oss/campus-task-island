# 独立模拟环境

生成器读取[数据设计](SIMULATION_DATASET.md)，按历史时间顺序通过业务服务回放50个用户的操作。产物在`.runtime/simulation/`下，不使用日常平台的`.runtime/campus.sqlite3`，也不依赖CAMPUS_DB_PATH环境变量。

## Windows一键启动

先按README完成项目依赖安装，然后双击项目根目录的`start_simulation.cmd`。脚本构建前端，首次生成并验收演示库，启动后自动打开 <http://127.0.0.1:8001/>；再次启动复用当前演示库，人工操作会保留。终端按Ctrl+C停止。

也可在项目根目录运行：

```powershell
.\start_simulation.ps1
# 生成新的演示并启动；保留旧目录
.\start_simulation.ps1 -New
# 换端口、不打开浏览器
.\start_simulation.ps1 -Port 8011 -NoBrowser
```

如果本机执行策略阻止直接运行ps1，使用cmd入口即可；它仅为本次子进程设置ExecutionPolicy，不修改系统策略。已启动的演示占用8001端口时，先停止原进程或换端口。

## Ubuntu

按README安装Python及前端依赖后：

```bash
bash start_simulation.sh
bash start_simulation.sh --new --port 8011 --no-browser
```

启动脚本在Windows验证；Ubuntu脚本遵循同一Python入口，本次未在Ubuntu主机实测。

## 生成与产物

Windows命令如下，Ubuntu将Python路径换为`.venv/bin/python`。

```powershell
# 仅生成和验收，默认观察时点为当前北京时间
.\.venv\Scripts\python.exe -X utf8 -m examples.simulation_dataset generate
# 指定时间与种子，重现文档中的业务ID和操作次序
.\.venv\Scripts\python.exe -X utf8 -m examples.simulation_dataset generate --at 2026-10-17T18:00:00+08:00 --seed 20261017
# 自定义输出必须是不存在的新目录
.\.venv\Scripts\python.exe -X utf8 -m examples.simulation_dataset generate --output .runtime/simulation/my-demo
```

`generate`每次新建目录，失败时不发布半成品；不会覆盖已有目录。位于项目`.runtime/simulation/`下的成功产物会更新该目录的`current.json`指针；自定义到其他位置时需要用`--directory`显式启动。

| 文件 | 内容 |
|---|---|
| demo.sqlite3 | 业务演示库，含50个模拟账号及3个兼容系统启动的内置账号 |
| accounts.json | 50个模拟账号的用户名、昵称、随机密码和设计编号；仅保存在本机运行目录 |
| demo.accounts.json | 3个内置演示账号的初始凭据，不参与50人故事 |
| manifest.json | 观察时点、种子、设计文档SHA256、所有业务ID映射 |
| events.json | 按时间排序的实际调用记录，记录设计编号和操作名，不包含密码 |
| snapshot.json | 原观察时点的120条主体内容快照 |
| acceptance.json / acceptance.md | 自动验收结果、计数和检查项 |

固定种子使业务ID、关系、操作和快照可复现；密码及登录令牌每次独立随机生成。数据库文件不会逐字节一致。生成器不调用模型、不联网；一键脚本首次安装npm依赖需要联网，手动使用引航员时仍遵循本机已有模型配置。

## 登录与体验

打开`.runtime/simulation/current.json`找到当前目录，再用其中的`accounts.json`登录。不要使用另一批生成目录的密码。

| 场景 | 登录账号 | 内容 |
|---|---|---|
| 选择申请人 | sim_u002 | T002，仍有两项待选申请 |
| 直接接取 | sim_u043 | T004，待接取 |
| 阶段补充 | sim_u014 | T020，先重新开始当前阶段再提交 |
| 审批变更 | sim_u004 | T026，延期提案待确认，原截止仍有效 |
| 候补递补 | sim_u003管理／sim_u020查看 | A011，U020候补第1 |
| 换岗历史 | sim_u009 | V003，旧J1已退出，新J2获位 |
| 时长更正 | sim_u001管理／sim_u009查看 | V017，原120失效，可重新核验110 |
| 撤回可见性 | sim_u049／其他用户 | D030仅作者可查原文与版本 |

实际ID查manifest.json中的ids，例如`ids.T020`对应`/#/tasks/<真实ID>`；已结束活动从“我的报名／我发布的活动”进入。完整故事见设计文档第7节。

## 时间与重复验收

默认观察时点为生成时的当前北京时间，历史和未来统一平移。运行时钟按“原观察时点+生成后的实际流逝时间”推进，重启不倒退；活动自然开放、截止和结束。GET `/api/simulation`可查看模拟时钟，接口不返回密码或本机路径。登录会话有效期使用真实时钟。

固定讲解可启动冻结时钟：

```powershell
.\start_simulation.ps1 -FreezeClock
# 指定旧目录；不改current指针
.\.venv\Scripts\python.exe -X utf8 -m examples.simulation_server --directory .runtime/simulation/my-demo --freeze-clock
# 验收当前演示，始终以原观察时点比较
.\.venv\Scripts\python.exe -X utf8 -m examples.simulation_dataset verify
```

验收会重新生成报告和快照，并执行登录、权限、重启持久化等HTTP检查。人工推进流程后，原始状态分布可能改变，重新验收会如实FAIL；这不代表人工操作失败。用`-New`重新生成基准演示即可，旧库保留。报告中的业务回放不代表真实学生行为，也不包含模型准确率或并发压力评测。

## 自动测试

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_simulation -v
```

测试使用临时目录，不改变当前演示指针，覆盖完整回放、50账号登录、权限隔离、固定种子复现、随机凭据、业务时钟隔离、手动操作持久化、失败不发布和禁止覆盖已有目录。
