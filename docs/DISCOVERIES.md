# 校园发现

## 使用入口

左侧“校园发现”查看列表；“发布任务”选择“校园发现”填写图文。所有登录用户可发布。
“我的空间 → 我的发现”保留本人发布和已撤回记录。普通任务首页和原接口保持兼容。

标题、说明、地点、发现时间、信息来源必填，来源默认“本人观察”。时间按北京时间填写，服务端拒绝无时区或未来时间。分类发布后固定。

| 分类 | 初始状态 | 可选状态 |
| --- | --- | --- |
| 公共设施问题 | 待核实 | 待核实、已核实、已反馈、处理中、已有结果 |
| 安全与通行提醒 | 有效 | 有效、已失效 |
| 有趣发现、校园生活分享 | 展示中 | 展示中、已过期 |

状态均为“发布者自报”，允许恢复活跃状态，每次说明原因。默认列表隐藏已有结果、已失效、已过期，选具体状态可查看历史内容。

## 评论、编辑和历史

评论为按时间分页的平铺结构，文字必填，可附3张图片。已结束发现仍可评论；评论者可撤回本人评论，之后只显示占位。
只有发布者可编辑正文、更新状态和撤回发现。三种操作共用 version，冲突返回409，网页保留输入。核对最新详情后可选择“使用最新版本并保留输入”，再提交。
公开详情只显示当前正文、状态说明历史和正文修改字段／时间。完整前后正文及旧图片引用仅发布者可在“本人完整编辑版本”查看。
撤回发现后，公开详情仅显示已撤回，不再返回正文、评论、图片。本人仍可查看历史，首版无恢复入口。
页面可见时每15秒刷新详情和评论，保持未提交的评论和编辑输入。

## 图片存储与访问

安装 requirements.txt，包括 Pillow 和 python-multipart。JPEG、PNG、WebP均按实际解码校验，单张不超过5MiB、2000万像素，不接受动画。服务端纠正方向、去除元数据、透明背景转白、最长边缩至4096像素，再编码为JPEG。
图片目录固定为数据库所在目录下的 discovery-media；临时数据库使用独立目录。暂存图24小时后在启动或后续上传时清理，已关联的旧图保留供本人查历史。
上传返回随机图片ID；只能引用本人上传且未用于其他发现／评论的图片。当前公开正文或未撤回评论的配图可匿名访问；移除或撤回后仅原上传者可读取。通过接口读取，未静态挂载整个目录。响应 no-store、Vary: Cookie、nosniff。
上传失败保留文字与待重试文件，上传成功不自动发布。

## API

| 方法与路径 | 用途 |
| --- | --- |
| GET /api/discoveries | keyword/category/status/limit/offset，默认活跃列表 |
| POST /api/discoveries | 登录发布；title/category/description/location/discovered_at/information_source/image_ids |
| GET /api/discoveries/{id} | 当前公开内容、server_time、状态及正文变更元信息；本人可读撤回记录 |
| PATCH /api/discoveries/{id} | 发布者完整提交正文六字段、image_ids及version，不允许改变category |
| POST /api/discoveries/{id}/status | 发布者提交version/status/reason |
| POST /api/discoveries/{id}/withdraw | 发布者提交version/reason |
| GET/POST /api/discoveries/{id}/comments | 分页读取／提交content及image_ids |
| POST /api/discovery-comments/{id}/withdraw | 评论者本人撤回 |
| POST /api/discovery-images | multipart/form-data，file字段 |
| GET /api/discovery-images/{id} | 按当前引用和上传者身份判断可见性 |
| GET /api/me/discoveries | 本人的全部发现及撤回记录，分页 |
| GET /api/discoveries/{id}/versions | 仅发布者可读完整正文版本 |

数据库新增 discoveries、discovery_comments、discovery_images、discovery_versions、discovery_status_history 五张表，schema版本8。写操作 BEGIN IMMEDIATE，在同一事务中检查作者、版本和撤回状态，避免编辑覆盖及撤回后的公开评论。

## 引航员范围

提示词区分普通任务、综素活动、志愿服务和校园发现。校园发现提供页面指引，不使用普通任务草稿，不开放AI发布、评论、状态修改或查询工具，不宣称已核实设施或安全情况。

## 验证

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
npm.cmd --prefix web run build
.\.venv\Scripts\python.exe -X utf8 -m examples.discovery_demo --port 8001
.\.venv\Scripts\python.exe -X utf8 -m examples.guide_type_check --output .runtime/evals/discovery-guide-real-latest.json
```

demo使用临时数据库，账号路径及合成图片路径写入.runtime/discovery-demo.json。访问localhost:8001以隔离正式127.0.0.1账号Cookie。真实模型评测会调用.env配置的模型，输入为合成场景。

2026-10-15：181项自动测试通过（原151项＋30项发现测试），TypeScript与Vite构建通过，真实Qwen3.8-Flash的8个内容类型场景通过。临时库双账号网页验证了发布配图、评论配图、本人评论撤回、状态变化、正文纠错、版本冲突保留输入、公开历史、图片移除权限、筛选、刷新和登录返回。

首版不含楼中楼、评论编辑、收藏、地图、自动过期、举报审核、工作人员认证或紧急联系渠道对接。

正式服务已更新：数据库备份 `.runtime/campus.before-discoveries-20261015-012718.sqlite3`；原24张表逐表行数与内容SHA256在迁移前后及服务启动后均一致。新增5张发现表，schema从7升至8。原库没有已有媒体文件。检查结果见 `.runtime/discovery-migration-report.json`，网页记录见 `.runtime/discovery-web-acceptance.json`。
