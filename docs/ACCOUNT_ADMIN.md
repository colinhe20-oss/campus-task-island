# 主机管理员账号维护

普通用户的“退出登录”仍然只结束登录。清理测试账号是独立的主机维护操作，没有网页入口、HTTP 接口或引航员工具。

## 权限与数据库

在运行服务的电脑上，**以管理员身份打开 PowerShell**，进入项目目录：

```powershell
cd E:\agent1
```

工具在 Windows 检查进程是否已提升管理员权限，在 Linux 检查是否为 root；普通权限直接拒绝列出、检查、删除及重置密码。它使用当前项目的 `.runtime/campus.sqlite3`；设置了 `CAMPUS_DB_PATH` 时与服务保持一致。也可在子命令之前明确指定路径：

```powershell
.\.venv\Scripts\python.exe -m campus.accounts --db "E:\agent1\.runtime\campus.sqlite3" list
```

每次命令都会显示实际数据库绝对路径。不存在或不兼容的库会报错，不会创建空库或自动迁移。迁移到其他电脑后，在新项目目录使用当地虚拟环境，默认路径会随项目位置变化。

权限隔离依赖操作系统：本工具检查管理员权限，数据库、备份和项目代码也应只交给可信的主机用户。已有数据库写权限的人仍可以绕过工具直接操作 SQLite；网页账号权限不能限制这种本机文件访问。若多人共用主机，应通过 Windows 文件权限或 Linux 文件权限限制这些文件的访问。

## 列出与检查

```powershell
.\.venv\Scripts\python.exe -m campus.accounts list
.\.venv\Scripts\python.exe -m campus.accounts inspect test.user
```

将 `test.user` 替换为实际账号名。列表只显示账号 ID、账号名、昵称及状态，不输出密码散列或会话凭证。检查结果包含：

- `id`：本次确认要操作的账号 ID。
- `can_delete`：是否允许删除。
- `protected_reason`：受保护的原因。
- `blockers`：阻止删除的关联表、字段和记录数量。
- `cleanup`：删除账号时一并移除的登录会话及旧版发布权限记录。

历史任务、已取消报名、已读消息、引航员对话或运行、草稿、上传图片等关联记录同样阻止删除，不只检查未完成业务。工具扫描数据库中指向账号的外键，新增关联表也默认阻止删除，不级联清空业务记录。

内置的 `publisher`、`helper`、`observer` 暂时受保护：服务启动会自动补建它们，且 `publisher` 承担旧数据的发布者兼容逻辑。本工具用于清理后来注册的闲置测试账号。

## 确认删除

先运行预览：

```powershell
.\.venv\Scripts\python.exe -m campus.accounts delete test.user
```

该命令不会删除任何内容。确认检查结果后，将下方 `完整账号ID` 替换为检查结果的 `id` 值，再执行：

```powershell
.\.venv\Scripts\python.exe -m campus.accounts delete test.user --confirm 完整账号ID
```

账号名和 ID 必须同时匹配；如果同名账号已被删除并重新注册，旧 ID 不能用于删除新账号。执行时在同一个写事务内重新检查关联记录，先生成完整 SQLite 备份并验证，再删除账号、会话及旧权限记录。备份失败则不删除；事务出错则回滚。

备份保存在数据库旁的 `<数据库文件名主干>.account-backups` 目录，成功时显示完整路径。默认是 `.runtime/campus.account-backups/`。备份是**整个数据库**，包含其他用户资料和密码散列，应按数据库同等权限保管；恢复整库会影响备份之后的全部业务，恢复前须停止服务并处理现有 WAL/SHM 文件，不要直接覆盖运行中的数据库。

成功删除后，账号所有旧会话失效，原密码不能登录。删除是物理删除，普通账号名可以再次注册，新账号使用新的 ID；备份仍保留删除前的数据。已有业务记录的账号不在本次删除范围内，需要另行设计数据保留方案。

## 重置密码

```powershell
.\.venv\Scripts\python.exe -m campus.accounts reset-password test.user
```

交互输入两次新密码，不输出明文；重置后原有会话全部失效，不更改业务数据。该命令也支持前置 `--db` 参数并要求主机管理员权限。演示账号初始密码 JSON 不随重置更新。
