# 校园任务岛模拟数据集设计 v1

> ⚠️ **已归档**：本文是第一版模拟数据规格，已被[第二版规格](SIMULATION_DATASET_V2_SPEC.md)替代，生成器现读取第二版规格。保留仅作历史参考。

本文是模拟生成器与多人操作演示的输入规格。实现与启动方法见[模拟环境使用说明](SIMULATION_USAGE.md)；生成器仅向独立演示目录写入账号及业务记录，不修改日常平台数据库。

## 1. 基准、口径与业务边界

- **50个账号、120条主体内容**：普通任务50、志愿活动20、综素／二课活动20、校园发现30。岗位、申请、成果、评论、历史版本、消息均为关联记录，不计入120条。
- **E = 2026-10-17T18:00:00+08:00**。历史窗口从2026-09-19T18:00:00+08:00开始，未来安排不晚于2026-11-07T18:00:00+08:00。文中所有时间表达式均以E为基准，可整体平移。
- `E-2d`表示2026-10-15 18:00；`E+1d-9h`表示2026-10-18 09:00。`C`表示该条内容发布时间，`B`表示首个报名操作时间；`+5m`表示在前一个明确基准上增加5分钟。未标明增量基准的连续操作均相对所在模板的C或B，不能累加解释。
- 校区、场所采用浙大校园背景；人物、社团、组织、来源公告均为虚构。昵称统一加“模拟·”，发布标题统一加“【模拟】”；表格省略这两个固定前缀。不得据此宣称真实学校活动、学分认定或设施故障。
- 编号U/T/V/A/D是设计键，不作为数据库主键。后续生成时保存设计键与真实ID映射；岗位键为`Vxxx-J1/J2/J3`，报名及成果按父项、用户、attempt或提交次数编号。
- 人物画像属于设计元数据。当前users只存账号资料，不新增专业、偏好、活跃度或权限角色字段。所有模拟账号均active；50个账号不包含系统内置的publisher/helper/observer。
- 本版不设计固定明文密码。未来生成账号时通过现有注册／鉴权逻辑设置密码，凭据单独放本机运行目录。本文不是可直接登录的账号清单。

### 1.1 数量与状态覆盖

| 对象 | 分组 | 数量 |
|---|---|---:|
| 用户 | 发布组织较多／高频／普通／低频 | 8／12／20／10 |
| 任务分类 | learning／creative／music／daily | 18／12／6／14 |
| 任务报酬 | mutual／paid | 32／18 |
| 任务接取 | approval／direct | 30／20 |
| 任务阶段 | 使用阶段／整项提交 | 12／38 |
| 任务存储状态 | published／in_progress／pending_review／completed／paused／cancelled | 14／16／6／8／3／3 |
| 综素活动标签 | second_class／aesthetic／ideological（每场单标签） | 10／6／4 |
| 综素时间分组 | 未开放／开放有位／开放满额／截止未开始／结束／取消 | 3／7／3／3／2／2 |
| 志愿主题 | 图书／环保／科普／赛事／引导 | 各4 |
| 志愿时间分组 | 未开放／开放有位／所有岗位满额／截止未开始／进行中／结束／取消 | 2／6／3／2／2／3／2 |
| 志愿岗位 | 双岗活动／三岗活动／岗位合计 | 12／8／48 |
| 两类活动报名方式 | 各自direct／review | 各10／10 |
| 发现分类 | facility／safety／interesting／life | 10／6／7／7 |

### 1.2 存储状态与展示结果

任务逾期不改变主状态；待接取过期用`is_expired`，进行中或待验收的逾期用`is_overdue`，暂停期间该标记为false。任务下架在数据库保留`published + is_listed=0`，TaskRead/API展示状态为withdrawn，不能把存储状态写成cancelled或withdrawn。

综素和志愿活动的`status`由服务端时间、取消标记、名额推导：`not_open/open/full/closed/cancelled`。本文“进行中”“已结束”是时间分组，API仍返回closed，结束或取消后不在默认大厅列表中。报名存储可为pending/registered/waitlisted/rejected/cancelled/activity_cancelled；活动或岗位开始后未处理的pending、waitlisted对外显示not_selected，不批量改写存储状态，也不因此自动生成消息。

校园发现的状态只能在对应分类内选择，来源始终是`author_report`。撤回记录保留原分类状态并写withdrawn_at，不新增withdrawn状态。默认发现列表排除终态resolved/invalid/expired及已撤回记录；终态可用状态筛选查看，撤回正文仅作者可见。

## 2. 50人名册

用户名固定为`sim_u001`至`sim_u050`；下表“账号后缀”补在`sim_`后。关联内容的完整反向索引见第8节，除该索引外不维护第二份关系真值。

| 用户 | 账号后缀 | 虚构昵称 | 年级／专业背景 | 兴趣与技能 | 活跃组 | 代表关联 |
|---|---|---|---|---|---|---|
| U001 | u001 | 林知远 | 大三／人工智能 | Python、科研互助、科普组织 | 组织 | T001、A001、V001 |
| U002 | u002 | 周予安 | 大三／计算机 | Web、项目管理、阅读 | 组织 | T002、A002、V002 |
| U003 | u003 | 沈清禾 | 大二／中文 | 写作、读书会、排版 | 组织 | T003、A003、V003 |
| U004 | u004 | 许景行 | 大三／机械 | CAD、赛事服务、维修科普 | 组织 | T004、A004、V004 |
| U005 | u005 | 陈星澜 | 大二／环境工程 | 环保、摄影、公益策划 | 组织 | T005、A005、V005 |
| U006 | u006 | 顾南舟 | 大三／数字媒体 | 海报、视频、展览组织 | 组织 | T006、A006、V006 |
| U007 | u007 | 叶初晴 | 大二／音乐相关方向 | 键盘、合唱、工作坊 | 组织 | T007、A007、V007 |
| U008 | u008 | 江以宁 | 大三／公共管理 | 志愿统筹、路线规划 | 组织 | T008、A008、V008 |
| U009 | u009 | 陆闻溪 | 大二／人工智能 | PyTorch、调试 | 高频 | T015、A011 |
| U010 | u010 | 苏映川 | 大二／计算机 | Git、前端 | 高频 | T016、V003 |
| U011 | u011 | 唐书白 | 大三／数学 | 统计、LaTeX | 高频 | T017、A012 |
| U012 | u012 | 宋晚棠 | 大二／设计 | 视觉设计、摄影 | 高频 | T018、V003 |
| U013 | u013 | 程亦航 | 大二／电子信息 | 电路、技术文档 | 高频 | T019、A012 |
| U014 | u014 | 梁雨桐 | 大三／新闻传播 | 采访、剪辑 | 高频 | T020、D001 |
| U015 | u015 | 方时序 | 大二／软件工程 | Python、Linux | 高频 | T021、V003 |
| U016 | u016 | 温见月 | 大二／建筑 | 手绘、空间观察 | 高频 | T022、A011 |
| U017 | u017 | 何沐辰 | 大三／物理 | 科普、器材整理 | 高频 | T023、V016 |
| U018 | u018 | 白若岚 | 大二／外语 | 翻译、活动引导 | 高频 | T024、A011 |
| U019 | u019 | 郑云帆 | 大三／自动化 | 数据处理、志愿服务 | 高频 | T025、V003 |
| U020 | u020 | 孟知夏 | 大二／社会学 | 调研、记录整理 | 高频 | T026、A011 |
| U021 | u021 | 韩亦可 | 大一／人工智能 | Python入门、科普 | 普通 | T009、A004 |
| U022 | u022 | 罗锦书 | 大二／历史 | 阅读、资料检索 | 普通 | T010、A004 |
| U023 | u023 | 邵星野 | 大一／工科试验班 | 制图、跑步 | 普通 | T011、A004 |
| U024 | u024 | 夏语宁 | 大二／教育 | 教学材料、公益 | 普通 | T012、A004 |
| U025 | u025 | 丁墨池 | 大一／中文 | 文案、朗读 | 普通 | T013、A005 |
| U026 | u026 | 魏澄 | 大二／生物 | 实验记录、自然观察 | 普通 | T014、A005 |
| U027 | u027 | 乔思齐 | 大二／计算机 | 算法、排版 | 普通 | T027、A005 |
| U028 | u028 | 袁鹿鸣 | 大一／经济 | 表格、预算 | 普通 | T028、A005 |
| U029 | u029 | 齐晓风 | 大二／材料 | 物料管理、羽毛球 | 普通 | T029、A006 |
| U030 | u030 | 樊舒然 | 大一／设计 | 插画、摄影 | 普通 | T030、A006 |
| U031 | u031 | 戴望舒 | 大二／数学 | 数据清理、桌游 | 普通 | A006、V009 |
| U032 | u032 | 纪泊言 | 大一／环境 | 分类回收、骑行 | 普通 | A006、V005 |
| U033 | u033 | 谢听澜 | 大二／外语 | 导览、阅读 | 普通 | A007、V007 |
| U034 | u034 | 潘予乐 | 大一／音乐相关方向 | 吉他、合唱 | 普通 | A007、V007 |
| U035 | u035 | 姜禾 | 大二／化学 | 科普、资料整理 | 普通 | A007、V008 |
| U036 | u036 | 于清越 | 大一／建筑 | 手工、展陈 | 普通 | A007、V008 |
| U037 | u037 | 蓝景 | 大二／地理信息 | 地图、路线规划 | 普通 | A008、V006 |
| U038 | u038 | 蒋若水 | 大一／医学相关方向 | 健康科普、记录 | 普通 | A008、V006 |
| U039 | u039 | 傅言蹊 | 大二／心理 | 问卷设计、沟通 | 普通 | A008、V009 |
| U040 | u040 | 彭念 | 大一／管理 | 现场引导、整理 | 普通 | A008、V009 |
| U041 | u041 | 蔡小满 | 大一／工科试验班 | 学习记录 | 低频 | T002首次申请后撤回 |
| U042 | u042 | 郁星 | 大一／理科试验班 | 科普阅读 | 低频 | A004首次报名待审核 |
| U043 | u043 | 柯北 | 大一／计算机 | 工具探索 | 低频 | T002首次申请后撤回 |
| U044 | u044 | 田雨声 | 大一／中文 | 阅读分享 | 低频 | A005首次报名后退出 |
| U045 | u045 | 杭一诺 | 大一／环境 | 校园环保 | 低频 | V005首次志愿报名 |
| U046 | u046 | 汪浅 | 大一／设计 | 校园摄影 | 低频 | D023首次发布 |
| U047 | u047 | 童栖 | 大一／公共管理 | 路线信息 | 低频 | D024首次发布 |
| U048 | u048 | 施晨 | 大一／外语 | 读书、整理 | 低频 | V004首次报名待审核 |
| U049 | u049 | 钱竹 | 大一／生物 | 自然观察 | 低频 | D030首次发布后撤回 |
| U050 | u050 | 安可 | 大一／数学 | 音乐、活动体验 | 低频 | A006首次报名后撤回 |

组织用户也参与他人内容：U001参加A011、U002参加A012、U003参加A013、U004参加A014、U005参加A015、U006参加A016、U007参加V016、U008参加V017。它们均不得由本人负责。

## 3. 普通任务50条

### 3.1 字段与操作模板

每行均提供`title/category/description/completion_criteria/location/deadline/reward_type/reward_amount_fen/acceptance_mode/publisher_id`。描述固定展开为“需要同学协助完成《标题》：验收栏所述内容；材料由发布者提供，可使用模拟材料，不涉及课程代做或真实个人资料。”互助reward为“无偿互助，完成后交流方法”；有偿reward为“固定报酬X元，验收后双方线下结算，平台仅记录确认”，金额以分存储。`无`即mutual且金额null；`¥X`即paid且金额为100X。

`申`=approval，申请字段规则reason=required、experience=optional、supplement=disabled；`直`=direct，三项规则均disabled，claim必须confirmed=true。申请理由默认“我愿意按《标题》的验收要求完成，可在截止前交付”，经验默认引用该用户名册技能。每次成果summary为“已完成：验收栏内容；请按约定核对”，退回后的summary必须点明修正项。

非故事覆盖的发布时间：T001—T014为C=E-7d；T015—T030为C=E-12d；T031—T036为C=E-10d；T037—T044为C=E-21d；T045—T050为C=E-15d。同组记录按编号每次递增5m；逐条故事指定时间优先，截止时间始终以表格为准。模板内“发布者”“接取者”均指该行用户。

| 模板 | 从C开始的操作链 | 观察时点结果 |
|---|---|---|
| P0 | 发布，不产生申请 | published，assignee=null |
| P1 | 发布；表内申请人按列出顺序在C+1h、+2h、+3h申请 | published，有pending申请 |
| P2 | P0/P1后，发布者C+1d下架 | published，is_listed=0；pending申请rejected |
| W | 发布；接取者C+1h申请、发布者C+2h选定（申），或C+1h claim（直） | in_progress |
| R | W后，C+3d整项submit | pending_review |
| F | R后，C+4d发布者review accept | completed |
| Q | W后，C+2d接取者propose_control pause；C+2d+1h发布者同意，extend_deadline=false | paused，paused_from_status=in_progress |
| X | W后，C+3d接取者propose_control cancel；C+3d+1h发布者同意 | cancelled；有偿取消另见故事 |

阶段任务用第3.3节代替W之后的整项submit/review。阶段计划在C+30m、任务尚未接取时，由发布者set_plan(expected_version=0)，每阶段均由assignee负责、publisher验收。接取后新增或替换阶段须走双方约定变更，不直接set_plan。

### 3.2 完整清单

`参与链`中的最后一个W/R/F/Q/X用户是唯一接取者；P1所列用户均为申请人。DB结果是主状态，附加标记另列。

| 编号 | 标题 | 分类 | 发布者 | 地点 | 验收标准 | 报酬 | 接取 | 截止（相对E） | 参与链／模板 | DB结果及附加情形 |
|---|---|---|---|---|---|---|---|---|---|---|
| T001 | Python环境排错互助 | learning | U001 | 紫金港学习共享空间 | 整理3个依赖冲突的原因与复现步骤 | 无 | 直 | +3d | P0 | published |
| T002 | 读书会资料索引整理 | learning | U002 | 紫金港图书馆讨论区 | 20条模拟文献索引，含主题与来源 | 无 | 申 | +4d | U009/U010/U041/U043申请，后两人撤回 | published，2条pending |
| T003 | LaTeX报告模板排版 | learning | U003 | 紫金港图书馆讨论区 | 8页模拟报告，无溢出版面 | ¥40 | 申 | +5d | P1：U011、U027 | published |
| T004 | Git分支练习说明整理 | learning | U004 | 紫金港学习共享空间 | 1份含6条命令的练习说明 | 无 | 直 | +2d | P0 | published |
| T005 | 概率统计概念卡片整理 | learning | U005 | 紫金港东教学区自习区 | 12张概念卡，注明例子与来源 | 无 | 申 | +6d | P1：U011、U031 | published |
| T006 | 英语口语互练安排 | learning | U006 | 紫金港学习共享空间 | 共同完成2轮模拟交流并记录反馈 | 无 | 直 | +7d | P0 | published |
| T007 | 开源项目安装说明校对 | learning | U007 | 紫金港学习共享空间 | 复核5步安装说明并给出错误清单 | ¥30 | 申 | +5d | P1：U010、U015 | published |
| T008 | 线性代数知识图示 | learning | U008 | 紫金港东教学区自习区 | 3幅矩阵运算图示及文字解释 | 无 | 直 | +4d | P0 | published |
| T009 | 科普讲稿术语核对 | learning | U021 | 紫金港图书馆讨论区 | 核对15个术语并标注公开来源 | 无 | 申 | -1d | P1：U017、U020 | published，已截止未接取 |
| T010 | 公开数据表格清理 | learning | U022 | 紫金港学习共享空间 | 清理100行虚构数据并提供规则说明 | ¥25 | 申 | -2d | P1：U019 | published，已截止未接取 |
| T011 | Linux命令速查卡整理 | learning | U023 | 紫金港学习共享空间 | 20条常用命令及安全练习示例 | 无 | 直 | -1d | P0 | published，已截止未接取 |
| T012 | 课程外阅读清单排版 | learning | U024 | 紫金港图书馆讨论区 | 将10条推荐书目排成可打印清单 | ¥20 | 申 | +5d | P2，原申请U012 | published，is_listed=0 |
| T013 | 校园科普题卡试读 | learning | U025 | 紫金港东教学区自习区 | 试读10题，反馈歧义与错字 | 无 | 直 | +6d | P2，无申请 | published，is_listed=0 |
| T014 | 文献管理方法交流 | learning | U026 | 紫金港图书馆讨论区 | 对比2种公开文献整理方法 | 无 | 申 | +7d | P1：U020 | published |
| T015 | PyTorch入门示例校对 | learning | U001 | 紫金港学习共享空间 | 校对2个教学示例及运行说明 | 无 | 直 | +5d | W：U009；阶段S1 | in_progress |
| T016 | 社团网页交互说明 | learning | U002 | 紫金港学习共享空间 | 输出3页交互说明及5项检查结果 | ¥60 | 申 | +6d | W：U010；阶段S2 | in_progress |
| T017 | 数据可视化读图说明 | learning | U003 | 紫金港图书馆讨论区 | 为3张模拟图写解释与局限 | 无 | 直 | +4d | W：U011；阶段S3 | in_progress |
| T018 | 科普海报文字核对 | learning | U004 | 紫金港东教学区自习区 | 校对5处技术解释及引用 | 无 | 申 | +5d | W：U012；阶段S4 | in_progress |
| T019 | 社团成果展海报 | creative | U005 | 紫金港学生活动中心 | 1张海报及可编辑源文件 | ¥80 | 申 | +7d | W：U013；阶段S5 | in_progress |
| T020 | 校园短片字幕制作 | creative | U006 | 紫金港学生活动中心 | 3分钟模拟短片字幕与校对表 | 无 | 申 | +6d | W：U014；阶段S6 | in_progress，阶段退回 |
| T021 | 读书角宣传配图 | creative | U007 | 紫金港图书馆公共区 | 3张配图，注明素材授权来源 | 无 | 直 | +4d | W：U015 | in_progress |
| T022 | 手作展位导视设计 | creative | U008 | 紫金港学生活动中心 | 4张方向牌及1份摆放说明 | ¥45 | 申 | +5d | W：U016 | in_progress |
| T023 | 科普图标草案整理 | creative | U001 | 紫金港学习共享空间 | 整理6个图标草案及使用说明 | 无 | 直 | +3d | W：U017 | in_progress |
| T024 | 双语导览折页排版 | creative | U002 | 紫金港学生活动中心 | 双面折页，检查中英文对应 | ¥50 | 申 | +4d | W：U018 | in_progress |
| T025 | 开源工具介绍长图 | creative | U003 | 紫金港学习共享空间 | 1张长图，覆盖3个工具及来源 | 无 | 直 | -1d | W：U019 | in_progress，逾期 |
| T026 | 社团招新文案润色 | creative | U004 | 紫金港学生活动中心 | 2版300字以内文案 | 无 | 申 | +5d | W：U020 | in_progress，故事5待确认变更 |
| T027 | 校园地图配色建议 | creative | U005 | 紫金港学习共享空间 | 2套配色及色觉可访问性说明 | ¥30 | 申 | +4d | W：U027 | in_progress |
| T028 | 展览标签排版互助 | creative | U006 | 紫金港学生活动中心 | 8张标签，统一尺寸与字体 | 无 | 直 | +3d | W：U028 | in_progress |
| T029 | 社团访谈录音文字整理 | creative | U007 | 紫金港学生活动中心 | 整理5分钟合成录音，标记不确定处 | ¥35 | 申 | -2d | W：U029 | in_progress，逾期 |
| T030 | 摄影作品说明整理 | creative | U008 | 紫金港学生活动中心 | 为6张模拟作品编写说明 | 无 | 申 | +5d | W：U030 | in_progress |
| T031 | 合唱排练资料编排 | music | U007 | 紫金港音乐排练空间 | 1份分声部资料及排练提示 | ¥40 | 申 | +3d | W：U011；阶段S7 | pending_review |
| T032 | 吉他入门练习卡设计 | music | U008 | 紫金港音乐排练空间 | 4张练习卡与节拍说明 | 无 | 直 | +4d | W：U014；阶段S8 | pending_review |
| T033 | 公开乐谱索引整理 | music | U001 | 紫金港图书馆讨论区 | 整理10份可合法使用的乐谱链接 | 无 | 申 | +2d | R：U017 | pending_review |
| T034 | 社团演出节目单排版 | music | U002 | 紫金港学生活动中心 | 2页模拟节目单，核对8个节目 | ¥30 | 申 | +3d | R：U018 | pending_review |
| T035 | 节奏练习音频互评 | music | U003 | 紫金港音乐排练空间 | 给出3段练习的节拍反馈 | 无 | 直 | +2d | R：U019 | pending_review |
| T036 | 校园音乐分享会曲目说明 | music | U004 | 紫金港图书馆讨论区 | 6首曲目简介与来源 | 无 | 申 | +3d | R：U020 | pending_review |
| T037 | 共享书架分类标签 | daily | U005 | 紫金港图书馆公共区 | 8张标签与书架分类说明 | 无 | 直 | -5d | W：U009；阶段S9 | completed |
| T038 | 社团物料清单整理 | daily | U006 | 紫金港学生活动中心 | 30项虚构物料清单及缺项核对 | ¥35 | 申 | -4d | W：U010；阶段S10 | completed，双方已确认结算 |
| T039 | 桌游规则卡校对 | daily | U007 | 紫金港学生活动中心 | 校对2页自制桌游规则卡 | 无 | 直 | -3d | F：U011；故事1 | completed |
| T040 | 二手交换摊位标牌 | daily | U008 | 紫金港学生活动中心 | 5张不含真实交易信息的标牌 | ¥30 | 申 | -2d | F：U012；故事3 | completed，付款方已确认 |
| T041 | 校园路线文字说明 | daily | U001 | 紫金港图书馆公共区 | 3条教学区步行路线说明 | 无 | 直 | -4d | F：U013 | completed |
| T042 | 读书会物资预算表 | daily | U002 | 紫金港学生活动中心 | 15项虚构预算及总额检查 | ¥25 | 申 | -3d | F：U014 | completed，结算待双方确认 |
| T043 | 共享雨伞提示卡校对 | daily | U003 | 紫金港图书馆公共区 | 校对6条借还提示 | 无 | 直 | -2d | F：U015 | completed |
| T044 | 志愿物料打包说明 | daily | U004 | 紫金港学生活动中心 | 编写3类物料的打包检查单 | ¥40 | 申 | -1d | F：U016 | completed，双方已确认结算 |
| T045 | 图书交换目录整理 | daily | U005 | 紫金港图书馆公共区 | 整理20项模拟交换书目 | 无 | 申 | +5d | W：U017；阶段S11；故事6 | paused |
| T046 | 环保摊位布置清单 | daily | U006 | 紫金港学生活动中心 | 整理10项布置物料与顺序 | 无 | 直 | +6d | W：U018；阶段S12；Q | paused |
| T047 | 社团衣物收纳标记 | daily | U007 | 紫金港学生活动中心 | 6类服装的收纳标签与清单 | 无 | 申 | -1d | Q：U019 | paused，截止已过；暂停期间is_overdue=false |
| T048 | 公益资料装袋说明 | daily | U008 | 紫金港学生活动中心 | 3种资料包的装袋检查单 | 无 | 直 | +3d | X：U020 | cancelled，无偿 |
| T049 | 临时展台物料整理 | daily | U001 | 紫金港学生活动中心 | 清点20项模拟展台物料 | ¥50 | 申 | +4d | X：U009；故事6 | cancelled，协商金额¥20，待收款确认 |
| T050 | 旧宣传册分类清单 | daily | U002 | 紫金港学生活动中心 | 整理4类模拟宣传册清单 | ¥30 | 申 | +3d | X：U010 | cancelled，协商金额0，无需付款 |

T004在观察时点仍待接取，故事1给出继续体验直接接取的入口；未来操作不计入历史活跃度。

### 3.3 十二份阶段计划

每份计划2阶段：标题为“范围核对”“交付复核”；阶段验收分别为“列出本任务验收项及输入材料，逐项确认”“交付任务表验收栏全部内容并说明核对结果”。两阶段均由接取者负责，发布者验收。计划确认是发布者set_plan写入，不虚构另一方的计划审批接口。

| 计划 | 任务 | 阶段1截止 | 阶段2截止 | E时阶段1／阶段2 | W之后的操作（相对C） |
|---|---|---|---|---|---|
| S1 | T015 | E+2d | E+5d | confirmed／in_progress | +1d开始1，+2d提交1，+2d+1h通过1，+3d开始2 |
| S2 | T016 | E+2d | E+6d | confirmed／not_started | +1d开始1，+2d提交1，+2d+1h通过1 |
| S3 | T017 | E+1d | E+4d | in_progress／not_started | +1d开始1 |
| S4 | T018 | E+2d | E+5d | not_started／not_started | 仅发布计划 |
| S5 | T019 | E+3d | E+7d | confirmed／in_progress | 同S1 |
| S6 | T020 | E+2d | E+6d | confirmed／changes_requested | 见故事4；不得执行模板之外的额外阶段动作 |
| S7 | T031 | E+1d | E+3d | confirmed／submitted | +1d开始1，+2d提交1，+2d+1h通过1，+3d开始2，+4d提交2 |
| S8 | T032 | E+1d | E+4d | submitted／not_started | +1d开始1，+2d提交1 |
| S9 | T037 | E-7d | E-5d | confirmed／confirmed | +1d开始1，+2d提交1，+2d+1h通过1，+3d开始2，+4d提交2，+4d+1h通过2 |
| S10 | T038 | E-6d | E-4d | confirmed／confirmed | 同S9；+5d付款方确认，+5d+1h收款方确认 |
| S11 | T045 | E+2d | E+5d | in_progress／not_started | 见故事6，暂停时保留阶段状态 |
| S12 | T046 | E+2d | E+6d | in_progress／not_started | +1d开始1；之后执行Q |

T040的¥30、T044的¥40在模板完成后C+5d由付款方确认；T044再于C+5d+1h由收款方确认。T042没有确认动作。T050在X提案明确cancellation_settlement_fen=0，不调用结算确认。

## 4. 综素／二课活动20条

### 4.1 通用字段与报名链

每行标题加模拟前缀，description为“围绕《标题》开展校内交流；内容为合成演示，按下列参与要求开展”。组织名固定按负责人映射：U001求知科普小组、U002代码共学小组、U003纸上读书小组、U004匠心实践小组、U005青叶环保小组、U006光影创作小组、U007和声交流小组、U008同行服务小组，均前缀“模拟·”。来源为“模拟组织公告／Axxx”，contact为“演示联系代号Uxxx（无真实联系方式）”。

recognition_description按标签分别为“模拟二课参与说明”“模拟美育参与说明”“模拟形策二参与说明”，统一追加“仅作活动方信息展示，不产生学校正式认定”。参与要求为“本校在读学生；按时到场，遵守现场安排；”加清单中的内容要求。capacity为下表名额。

发布时间C=E-18d+(编号-1)×4h；未开放三场的O=E+1d，其余O=E-10d；除指定的取消记录外，B=E-9d。表中S为开始时间，结束F=S+2h；截止L对未开放场次为S-1d，对开放／满额场次为E+1d，对截止未开始场次为E-1h，对已结束场次为S-1d，对取消场次为E+1d。四个业务时间与发布时间均可按此唯一展开。

报名链记法：`r用户`=register，direct直接获得名额；review先pending再由负责人review approve。`p用户`=仅申请保持pending；`j用户`=申请后由负责人review reject，reason“申请说明未满足本场准备要求”；`w用户`=报名并在需要时审核通过，名额已满后候补；`x用户`=报名／申请后本人cancel_registration。

每行按从左到右的顺序，依次在B+0m、+10m、+20m……执行报名；review审核在各自报名后+2m；x的取消在其报名后+3m。真实候补序号只由实际入队顺序生成。报名说明为“我已阅读《标题》的参与要求，愿按时参加并完成准备”。负责人不能出现在本场参与链。取消活动统一在E-1d由负责人cancel，reason“模拟场地调整，本场取消”，且仅在参与链完成之后执行。

### 4.2 完整活动清单

标签：二课=second_class，美育=aesthetic，形策=ideological。以下时间均为相对E。

| 编号 | 标题／内容要求 | 标签 | 负责人 | 地点 | 名额 | 方式 | S | 参与链（B起） | E时分组／API状态与报名结果 |
|---|---|---|---|---|---:|---|---|---|---|
| A001 | AI工具与学习方法交流／带一个学习问题 | 二课 | U001 | 紫金港学习共享空间 | 8 | direct | +15d-9h | 无，尚未开放 | 未开放／not_open |
| A002 | Git协作入门讲座／阅读基础术语表 | 二课 | U002 | 紫金港东教学区讨论室 | 8 | review | +16d-9h | 无，尚未开放 | 未开放／not_open |
| A003 | 文献检索与阅读工作坊／自选一个主题 | 二课 | U003 | 紫金港图书馆讨论区 | 8 | direct | +17d-9h | 无，尚未开放 | 未开放／not_open |
| A004 | 科学问题拆解讨论／准备一个现象问题 | 二课 | U004 | 紫金港东教学区讨论室 | 6 | review | +3d-9h | rU021、rU022、rU023、pU024、pU042 | 开放有位／open；3 registered、2 pending |
| A005 | 低碳校园实践分享／准备一项减废建议 | 二课 | U005 | 紫金港学生活动中心 | 6 | direct | +4d-9h | rU025、rU026、rU027、rU028、xU044 | 开放有位／open；4 registered、1 cancelled |
| A006 | 媒体素养案例交流／阅读合成案例 | 二课 | U006 | 紫金港学生活动中心 | 6 | review | +5d-9h | rU029、rU030、rU031、rU032、xU050 | 开放有位／open；4 registered、1 cancelled |
| A007 | 学习互助经验圆桌／准备个人方法说明 | 二课 | U007 | 紫金港图书馆讨论区 | 6 | direct | +6d-9h | rU033、rU034、rU035、rU036 | 开放有位／open；4 registered |
| A008 | 公益项目设计交流／阅读参与者需求 | 二课 | U008 | 紫金港学生活动中心 | 6 | review | +7d-9h | rU037、rU038、pU039、pU040 | 开放有位／open；2 registered、2 pending |
| A009 | 开源项目阅读分享／选择一个公开仓库 | 二课 | U001 | 紫金港学习共享空间 | 8 | direct | +8d-9h | rU009、rU010、rU011、rU012、rU013、rU014 | 开放有位／open；6 registered |
| A010 | 科研记录方法工作坊／带一份模拟记录 | 二课 | U002 | 紫金港图书馆讨论区 | 8 | review | +9d-9h | rU015、rU016、rU017、rU018、pU019、pU020 | 开放有位／open；4 registered、2 pending |
| A011 | 校园摄影构图小组／自备任意拍摄设备 | 美育 | U003 | 紫金港学生活动中心 | 3 | direct | +2d-9h | rU001、rU009、rU016、wU018、wU020；U009退出 | 满额／full；U001/U016/U018 registered，U020候补第1；故事8 |
| A012 | 手绘明信片体验／自备纸笔 | 美育 | U004 | 紫金港学生活动中心 | 3 | review | +2d-6h | rU002、rU011、rU013、wU015 | 满额／full；3 registered、U015候补第1 |
| A013 | 校园色彩观察／准备一个色彩主题 | 美育 | U005 | 紫金港图书馆公共区 | 2 | direct | +2d-3h | rU003、rU010、wU012 | 满额／full；2 registered、U012候补第1 |
| A014 | 海报字体赏析／阅读2张模拟海报 | 美育 | U006 | 紫金港学生活动中心 | 4 | review | +1d-9h | rU004、rU014、pU017、jU019 | 截止未开始／closed；2 registered、1 pending、1 rejected |
| A015 | 合唱作品聆听交流／准备一段聆听感受 | 美育 | U007 | 紫金港音乐排练空间 | 4 | direct | +1d-6h | rU005、rU015、xU018 | 截止未开始／closed；2 registered、1 cancelled |
| A016 | 展陈叙事体验／阅读作品说明 | 美育 | U008 | 紫金港学生活动中心 | 4 | review | +1d-3h | rU006、rU016、pU020 | 截止未开始／closed；2 registered、1 pending |
| A017 | 校园公共议题读书讨论／阅读模拟材料 | 形策 | U001 | 紫金港图书馆讨论区 | 2 | direct | -4d-9h | rU009、rU011、wU013 | 已结束／closed；U013存waitlisted、展示not_selected |
| A018 | 社会实践观察交流／提交主题说明 | 形策 | U002 | 紫金港东教学区讨论室 | 2 | review | -3d-9h | U010先拒后重申通过、pU012、jU014、rU016 | 已结束／closed；U010/U016 registered，U012存pending展示not_selected；故事9 |
| A019 | 青年公益阅读交流／阅读模拟材料 | 形策 | U003 | 紫金港图书馆讨论区 | 4 | direct | +3d-5h | rU017、rU019；整场取消 | 取消／cancelled；2 activity_cancelled |
| A020 | 社会调研方法讨论／提交问题提纲 | 形策 | U004 | 紫金港东教学区讨论室 | 4 | review | +4d-5h | pU018、rU020；整场取消 | 取消／cancelled；2 activity_cancelled |

活动报名成功不生成学分记录；A017/A018的registered仅表示曾获报名名额，不能据此声称实际到场或获得认定。A011的退出时间以故事8为准；其余无额外动作。

## 5. 志愿活动20条、岗位48个

### 5.1 通用字段、时间与岗位规格

organization_name、information_source、contact沿用第4.1节映射，来源编号改Vxxx。description为“《标题》的模拟公益服务，按岗位说明分工，不使用真实服务对象资料”。recognition_conditions为“活动负责人根据实际参与登记核验分钟数；缺席为0；活动方确认不等于学校认定”。

每场的C=E-18d+(编号-1)×4h；V001/V002的O=E+1d，其余O=E-10d；B=E-9d。活动S见清单，F=S+2h。未开放场次L=S-1d；开放／满额场次L=E+1d；截止未开始场次L=E-1h；进行中、结束和取消场次L=S-1d。V020的取消发生在服务开始后，详见故事11。

48个岗位均提供name、description、requirements、location、starts_at、ends_at、capacity、estimated_minutes、estimated_hours_description。每岗起止=S/F，地点继承活动地点，预计分钟数=120，说明“预计120分钟，最终按实际参与由活动方核验”。requirements为“本校在读学生，能全程参加；阅读岗位工作说明”；description由下表按主题展开。两个／三个岗位同时服务，同一人同一活动最多保留一项有效报名。

| 主题 | J1名称／工作内容 | J2名称／工作内容 | J3名称／工作内容（仅三岗场） |
|---|---|---|---|
| 图书 | 分类整理岗／按模拟目录分类书目 | 标签核对岗／检查分类标签与清单 | 阅读引导岗／向参与者说明分类规则 |
| 环保 | 物料整理岗／整理演示回收物料 | 宣传引导岗／解释模拟分类规则 | 数据记录岗／记录匿名合成统计数量 |
| 科普 | 展台说明岗／介绍公开科普材料 | 材料准备岗／整理演示教学材料 | 体验引导岗／引导参与者完成模拟实验 |
| 赛事 | 路线引导岗／按模拟路线提示方向 | 物资整理岗／核对虚构物料清单 | 信息记录岗／记录模拟服务安排 |
| 引导 | 场地导览岗／介绍公共空间路线 | 资料分发岗／整理并分发模拟资料 | 问询说明岗／解释公开场所信息 |

岗位名额：V009/V010/V011每岗2人；其余每岗3人。每行中J1/J2/J3分别列出参与链，r/p/j/w/x含义及操作时点沿用第4.1节，review由本场负责人操作。每个岗位从B开始依次+10m报名，不同岗位可同时操作。报名说明追加“申请Jx，已阅读岗位要求”。取消V019的时间为E-1d；取消原因同“模拟场地调整”。

### 5.2 完整活动及岗位清单

| 编号 | 标题 | 主题 | 负责人 | 地点 | 方式 | 岗位数 | S（相对E） | J1参与链 | J2参与链 | J3参与链 | E时分组／结果 |
|---|---|---|---|---|---|---:|---|---|---|---|---|
| V001 | 图书角分类服务一期 | 图书 | U001 | 紫金港图书馆公共区 | direct | 3 | +18d-9h | 无 | 无 | 无 | 未开放／not_open |
| V002 | 图书角标签整理 | 图书 | U002 | 紫金港图书馆公共区 | review | 3 | +19d-9h | 无 | 无 | 无 | 未开放／not_open |
| V003 | 共享书目整理服务 | 图书 | U003 | 紫金港图书馆公共区 | direct | 3 | +4d-5h | rU009、rU010、rU011、wU012、wU015；U009换岗退出 | rU016、rU018；U009换入 | rU019、rU020 | 开放有位／open；J1满、J2满、J3余1 |
| V004 | 图书阅读引导服务 | 图书 | U004 | 紫金港图书馆公共区 | review | 3 | +5d-5h | rU011、pU021、pU048 | rU013、rU022 | rU015、pU023 | 开放有位／open；J1/J2/J3获位1/2/1 |
| V005 | 低碳物料整理服务 | 环保 | U005 | 紫金港学生活动中心 | direct | 3 | +6d-5h | rU017、rU024 | rU019、rU025 | rU032、rU045 | 开放有位／open；各岗获位2 |
| V006 | 环保宣传引导服务 | 环保 | U006 | 紫金港学生活动中心 | review | 3 | +7d-5h | rU009、pU026 | rU011、rU037 | rU013、rU038 | 开放有位／open；各岗获位1/2/2 |
| V007 | 分类回收科普服务 | 环保 | U007 | 紫金港东教学区公共区 | direct | 3 | +8d-5h | rU010、rU027 | rU012、rU033 | rU014、rU034 | 开放有位／open；各岗获位2 |
| V008 | 减废行动物料服务 | 环保 | U008 | 紫金港学生活动中心 | review | 3 | +9d-5h | rU015、pU028 | rU017、rU035 | rU019、rU036 | 开放有位／open；各岗获位1/2/2 |
| V009 | AI科普展台服务 | 科普 | U001 | 紫金港学生活动中心 | direct | 2 | +10d-9h | rU009、rU031、wU039 | rU011、rU040、wU020 | — | 全岗满额／full；每岗2 registered、1 waitlisted |
| V010 | 开源工具科普服务 | 科普 | U002 | 紫金港学习共享空间 | review | 2 | +11d-9h | rU010、rU012、wU014 | rU016、rU018、wU020 | — | 全岗满额／full；每岗2 registered、1 waitlisted |
| V011 | 科学实验体验服务 | 科普 | U003 | 紫金港东教学区公共区 | direct | 2 | +12d-9h | rU013、rU015、wU017 | rU019、rU020、wU009 | — | 全岗满额／full；每岗2 registered、1 waitlisted |
| V012 | 公益科普材料服务 | 科普 | U004 | 紫金港学生活动中心 | review | 2 | +1d-5h | rU010、pU021 | rU012、jU022 | — | 截止未开始／closed；2 registered、1 pending、1 rejected |
| V013 | 校园跑步路线服务 | 赛事 | U005 | 紫金港运动场公共区 | direct | 2 | +1d-1h | rU009、rU023 | rU011、xU024 | — | 截止未开始／closed；3 registered、1 cancelled |
| V014 | 趣味运动物资服务 | 赛事 | U006 | 紫金港运动场公共区 | review | 2 | -110m | rU013、rU025 | rU014、pU026 | — | 进行中／closed；U026存pending展示not_selected |
| V015 | 社团赛事信息服务 | 赛事 | U007 | 紫金港运动场公共区 | direct | 2 | -1h | rU015、rU027 | rU016、rU028 | — | 进行中／closed；4 registered |
| V016 | 运动会场地说明服务 | 赛事 | U008 | 紫金港运动场公共区 | review | 2 | -2d-9h | rU017、rU029、rU007 | rU018、rU030 | — | 已结束／closed；5 registered，见时长表 |
| V017 | 校园公共空间导览 | 引导 | U001 | 紫金港图书馆公共区 | direct | 2 | -2d-5h | rU009、rU031、rU008 | rU011、rU032 | — | 已结束／closed；5 registered，见时长表 |
| V018 | 读书交流资料服务 | 引导 | U002 | 紫金港图书馆公共区 | review | 2 | -1d-9h | rU010、rU033 | rU012、rU034 | — | 已结束／closed；4 registered，见时长表 |
| V019 | 科普开放日导览服务 | 引导 | U003 | 紫金港东教学区公共区 | direct | 2 | +3d-1h | rU017、rU035 | rU019、rU036 | — | 取消／cancelled；4 activity_cancelled，无核验资格 |
| V020 | 公益交流问询服务 | 引导 | U004 | 紫金港学生活动中心 | review | 2 | -1d-5h | rU013、rU037 | rU014、rU038 | — | 服务中取消／cancelled；4 activity_cancelled，保留资格 |

V001/V002观察时点未开放，没有报名历史。V016-J1与V017-J1均为3人容量，组织用户的交叉参与计入该名额。

### 5.3 参与登记与时长记录

只对下表指定报名登记；其他已有资格但未列出的记录保持初始version=0、attendance=null、confirmed_minutes=null。每场在F+10m登记，若确认则F+20m确认；V014/V015在E-10m登记。attendance均为participated，除明确标absent者。首次登记调用ParticipationInput(version=0)，确认携带登记后的version=1。确认后最新version=2。

| 报名 | 实际分钟 | 确认分钟 | 最新版本／E时记录状态 | 说明 |
|---|---:|---|---|---|
| V014-J1／U013 | 90 | null | 1／in_service | 已进行100分钟时登记90，服务尚未结束 |
| V014-J1／U025 | 0 | null | 1／in_service | absent，模拟临时无法到场 |
| V015-J1／U015 | 40 | null | 1／in_service | 已进行50分钟时登记40，不能提前确认 |
| V016-J1／U017 | 120 | 120 | 2／confirmed | 完整完成路线提示 |
| V016-J1／U029 | 100 | null | 1／pending_verification | 已登记，保留负责人待办 |
| V016-J1／U007 | 110 | 110 | 2／confirmed | 组织用户参与他人活动 |
| V016-J2／U018 | 0 | 0 | 2／confirmed | absent；reason“未到场，不予计时” |
| V016-J2／U030 | 90 | 90 | 2／confirmed | 按实际服务核验 |
| V017-J1／U009 | 110 | null | 3／pending_verification | 先实际120、确认120，再更正实际110；旧确认失效，故事11 |
| V017-J1／U031 | 120 | 120 | 2／confirmed | 已完成导览说明 |
| V017-J1／U008 | 100 | 100 | 2／confirmed | 组织用户参与他人活动 |
| V017-J2／U011 | 100 | 90 | 3／confirmed | 原确认100，更正确认90，reason“扣除未实际服务的休息时间” |
| V017-J2／U032 | 0 | 0 | 2／confirmed | absent；reason“未到场，不予计时” |
| V018-J1／U010 | 120 | 120 | 2／confirmed | 已完成资料服务 |
| V018-J1／U033 | 80 | 80 | 2／confirmed | 按实际服务核验 |
| V018-J2／U012 | 100 | null | 1／pending_verification | 等待负责人核验 |
| V018-J2／U034 | 0 | null | 0／pending_verification | 尚未登记，attendance=null，0只是默认值 |
| V020-J1／U013 | 40 | 40 | 2／confirmed | 取消前服务50分钟，实际40，F前因取消可确认 |
| V020-J1／U037 | 0 | null | 0／pending_verification | 保留资格，尚未登记 |
| V020-J2／U014 | 45 | null | 1／pending_verification | 取消后登记45，待确认 |
| V020-J2／U038 | 0 | 0 | 2／confirmed | absent；reason“未实际参与，不予计时” |

更正时填写reason，并使用当前版本；所有description为“按《活动标题》岗位工作说明完成实际服务／未到场”。V017两项更正在F+30m执行。V020在S+50m取消，S+60m登记、S+70m确认，不套用F+10m模板。全体official_status=not_connected、official_minutes=null，个人合计仅累加最新confirmed_minutes，null计0但不可展示为已确认0。

## 6. 校园发现30条

### 6.1 正文与历史模板

每条C=E-8d+(编号-1)×4h，discovered_at=C-30m，information_source为“虚构校园观察／Dxxx，仅供模拟演示”，image_ids=[]，不预设不存在的图片ID。description为表中观察说明追加“本条为模拟记录，状态由发布者自报”。第一版使用纯文本发现和评论，图文能力不作为本次验收条件。

按分类初始状态发布：facility=unverified、safety=valid、interesting/life=visible。每行评论者按顺序在C+1h、+2h评论，正文采用该行补充说明（有两人时第二人追加“补充观察，建议发布者复核”），各自保留评论ID。作者更新状态每次间隔1h，从C+1d起；reason为“根据模拟补充信息，发布者复核后更新”。编辑在C+3h，由作者将description追加“已补充具体位置”；完整提交DiscoveryFields并带当前version。评论不增加发现正文version。

标明“撤回”的发现，在所有评论、编辑和状态变化之后，由作者于C+2d撤回，reason“模拟信息已失去时效，撤回原文”。D001和D030具体动作由故事12覆盖。

| 编号 | 标题 | 分类 | 作者 | 地点 | 观察说明／评论补充说明 | 评论者（依序） | 作者操作链及E时结果 |
|---|---|---|---|---|---|---|---|
| D001 | 讨论区插座接触提示 | facility | U021 | 紫金港图书馆讨论区 | 模拟插座接触不稳定，需进一步复核／补充桌位与现象 | U009、U014 | unverified→verified→reported→in_progress→resolved；编辑；故事12 |
| D002 | 公共区桌面标识模糊 | facility | U022 | 紫金港图书馆公共区 | 模拟桌面编号不清／补充对应区域 | U010 | unverified；编辑 |
| D003 | 讨论室门牌指示不清 | facility | U023 | 紫金港东教学区公共区 | 模拟门牌箭头易混淆／补充走廊位置 | U011、U015 | unverified→verified |
| D004 | 公共书架层签缺失 | facility | U024 | 紫金港图书馆公共区 | 模拟层签缺失，查找不便／补充书架编号 | U012 | unverified→verified→reported |
| D005 | 活动区展架脚垫松动 | facility | U025 | 紫金港学生活动中心 | 模拟展架脚垫需检查／补充展架位置 | U013、U016 | unverified→verified→reported→in_progress |
| D006 | 路线牌印字不清 | facility | U026 | 紫金港运动场公共区 | 模拟路线牌文字褪色／补充方向和文字 | U014 | unverified→verified→reported→in_progress→resolved |
| D007 | 自习区时钟读数模糊 | facility | U027 | 紫金港东教学区公共区 | 模拟时钟显示不清／补充观察角度 | U015 | unverified |
| D008 | 共享资料盒标签脱落 | facility | U028 | 紫金港学习共享空间 | 模拟资料盒缺少分类标签／补充盒号 | U016、U019 | unverified→verified；编辑 |
| D009 | 活动室指示贴缺角 | facility | U029 | 紫金港学生活动中心 | 模拟地面指示贴不完整／补充缺损范围 | U017 | unverified→verified→reported |
| D010 | 书架导向图需更新 | facility | U030 | 紫金港图书馆公共区 | 模拟图示与摆放不一致／补充当前分类 | U018、U020 | unverified→verified→reported→in_progress |
| D011 | 雨后路面慢行提示 | safety | U031 | 紫金港图书馆外公共步道 | 模拟雨后路面湿滑，提醒慢行／补充湿滑区域 | U009、U019 | valid |
| D012 | 活动区临时绕行提醒 | safety | U032 | 紫金港学生活动中心 | 模拟物料整理期间建议绕行／补充替代路线 | U010 | valid；编辑 |
| D013 | 跑步路线交叉点提醒 | safety | U033 | 紫金港运动场公共区 | 模拟交叉路口注意避让／补充经过时段 | U011、U017 | valid |
| D014 | 湿滑区域恢复提示 | safety | U034 | 紫金港东教学区外步道 | 模拟积水已清理，待作者核对／补充复核观察 | U012 | valid→invalid |
| D015 | 临时障碍已移除 | safety | U035 | 紫金港学习共享空间外步道 | 模拟临时堆放物移走／补充通行情况 | U013、U018 | valid→invalid |
| D016 | 绕行信息更正 | safety | U036 | 紫金港学生活动中心 | 模拟绕行提示对应位置有误／补充正确位置 | U014 | valid→invalid；编辑 |
| D017 | 图书馆窗边光影观察 | interesting | U037 | 紫金港图书馆公共区 | 模拟午后光影适合观察／补充观察方向 | U015、U020 | visible |
| D018 | 校园树叶配色记录 | interesting | U038 | 紫金港公共步道 | 模拟秋叶颜色变化／补充树叶配色 | U016 | visible |
| D019 | 科普展板趣味问答 | interesting | U039 | 紫金港学生活动中心 | 模拟展板上的趣味题／补充另一种解释 | U017、U009 | visible；编辑 |
| D020 | 阅读角主题摆放 | interesting | U040 | 紫金港图书馆公共区 | 模拟主题书架摆放／补充主题关键词 | U018 | visible |
| D021 | 模拟手作图案分享 | interesting | U005 | 紫金港学生活动中心 | 模拟手作中的几何图案／补充构图建议 | U019、U010 | visible |
| D022 | 临时作品展示结束 | interesting | U006 | 紫金港学生活动中心 | 模拟短期展示已结束／补充撤展时间 | U020 | visible→expired |
| D023 | 窗边晚霞观察记录 | interesting | U046 | 紫金港图书馆公共区 | 模拟晚霞观察时段结束／补充观察方位 | U011 | visible→expired |
| D024 | 图书馆讨论区路线说明 | life | U047 | 紫金港图书馆公共区 | 模拟从公共入口前往讨论区／补充一个转弯点 | U012 | visible；编辑 |
| D025 | 自习用品整理方法 | life | U001 | 紫金港学习共享空间 | 模拟文具与资料分类方法／补充收纳建议 | U013、U017 | visible |
| D026 | 活动中心公共空间介绍 | life | U002 | 紫金港学生活动中心 | 模拟活动空间用途说明／补充导视位置 | U014 | visible |
| D027 | 校园步行路线备忘 | life | U003 | 紫金港公共步道 | 模拟教学区至图书馆路线／补充步行节点 | U015、U018 | visible |
| D028 | 临时物料借用说明结束 | life | U004 | 紫金港学生活动中心 | 模拟借用说明窗口结束／补充截止信息 | U016 | visible→expired |
| D029 | 模拟阅读活动指引过期 | life | U007 | 紫金港图书馆公共区 | 模拟临时阅读安排已结束／补充时间更正 | U019 | visible→expired |
| D030 | 资料领取地点说明撤回 | life | U049 | 紫金港学生活动中心 | 模拟领取说明存在地点歧义／补充位置问题 | U020、U010 | visible→expired后撤回；故事12 |

设施每种状态2条；安全valid/invalid各3条；趣闻visible5、expired2；生活visible4、expired3（其中D030撤回）。作者状态变化不代表后台已接报或完成维修，不生成不存在的工作人员账号。

## 7. 十二条详细交互故事

本节具体时间、参与者和操作替换对应通用模板，不叠加重复执行。观察时点之后的“下一步”仅为可继续体验的建议，不写入历史，不保证操作后仍保持本规格的状态分布。URL中的`{Txxx}`等须先映射真实ID。

### 故事1：直接接取并完成（T039）

登录U007（发布者）、U011（接取者），查看`/#/tasks/{T039}`。

| 时间 | 操作者／服务操作 | 结果 |
|---|---|---|
| E-21d | U007 create_task，direct、mutual，验收标准为校对2页规则卡 | published |
| E-21d+1h | U011 claim(confirmed=true) | in_progress，assignee=U011 |
| E-18d | U011 submit“已校对2页规则卡，补充了回合顺序说明” | pending_review |
| E-17d | U007 review accept | completed；U011收到完成消息 |

E时两人可查看成果。继续体验可由U043打开仍published的T004直接接取；这是未来动作，不改变U043已有历史。

### 故事2：多人申请、撤回与选定（T002、T024）

登录U002、U009、U010、U041、U043，查看`/#/tasks/{T002}`；另用T024展示已选定后的历史。

| 时间 | 操作 | 结果 |
|---|---|---|
| E-7d | U002发布T002，approval | published |
| E-7d+1h／+2h | U009、U010依次apply，说明“擅长资料检索”／“愿整理条目结构” | 两项pending |
| E-7d+3h／+4h | U041、U043依次apply | 四项pending |
| E-7d+5h／+6h | U041、U043各withdraw_application自己的申请 | 两项withdrawn，两项pending |
| T024的C+1h／+90m／+2h | U018、U020依次申请；U002选定U018 | U018 accepted、U020 rejected；T024 in_progress |

T024覆盖通用W，不再重复选定。E时U002可在T002选定U009或U010；其他人的申请说明仅按工作区权限查看。

### 故事3：成果退回、补充后通过（T040）

登录U008、U012，查看`/#/tasks/{T040}`，整项成果工作区。

| 时间 | 操作 | 结果 |
|---|---|---|
| E-21d+15m | U008发布 | published |
| C+1h／+2h | U012申请、U008选定 | in_progress |
| C+3d | U012 submit“已完成5张标牌” | pending_review，提交1 |
| C+3d+1h | U008 request_changes，feedback“第3张缺少使用说明，请补充后重交” | in_progress，提交1 changes_requested |
| C+4d／+4d+1h | U012提交修正版；U008 accept | 提交2 accepted，completed |
| C+5d | U008结算付款确认 | payer=true、payee=false，settlement version=1 |

E时U012可核对线下收款事实后确认收款；不存在平台转账记录。

### 故事4：阶段顺序与退回（T020／S6）

登录U006、U014，查看`/#/tasks/{T020}`阶段面板。C=E-12d+25m。

| 时间 | 操作 | 结果 |
|---|---|---|
| C | U006发布 | published |
| C+30m | U006 set_plan(expected_version=0)，采用S6两阶段 | plan_version=1，两阶段not_started |
| C+1h／+2h | U014申请、U006选定 | in_progress |
| C+1d／+2d／+2d+1h | U014 start阶段1、submit阶段1；U006 accept | 阶段1 confirmed |
| C+3d／+4d | U014 start阶段2、submit阶段2 | 阶段2 submitted，任务pending_review |
| C+4d+1h | U006 request_changes，feedback“字幕第40秒人名为合成代号，请与说明表统一” | 阶段2 changes_requested，任务in_progress |

阶段执行version从1起，每个start/submit/review各加1：E时阶段1 version=4，阶段2 version=4。下一步U014先start阶段2，再submit；不能对阶段任务走整项submit。

### 故事5：约定变更、延期和待确认提案（T026）

登录U004、U020，查看`/#/tasks/{T026}`约定面板。C=E-12d+55m。

| 时间 | 操作 | 结果 |
|---|---|---|
| C／+1h／+2h | 发布、申请、选定；原截止E+3d、原标准“1版300字以内文案” | terms_version=1 |
| C+3d | U020 changes.propose，reason“补充活动背景，需要增加比较版本”；patch completion_criteria改“2版300字以内文案”、deadline改E+5d | pending；旧约定继续有效 |
| C+3d+1h | U004 decide approve | terms_version=2；任务表展示新标准与新截止 |
| E-2h | U020再次propose延期至E+7d，reason“希望留出额外校对时间” | pending；E时仍按E+5d执行 |

下一步U004可同意或拒绝第二次申请；拒绝需理由。不得让申请者审批自己的提案；若先推进成果提交使提案失效，应按真实服务结果记录。

### 故事6：暂停、恢复与协商取消（T045、T049、T050）

T045登录U005/U017，T049登录U001/U009，分别查看任务详情的协作面板。T045的C=E-15d，T049的C=E-15d+20m。

| 时间 | 任务／操作 | 结果 |
|---|---|---|
| T045 C至C+2h | 发布、C+30m设置S11、申请、选定 | in_progress |
| C+1d | U017 start阶段1 | 阶段1 in_progress |
| C+2d／+2d+1h | U017申请pause，reason“等待模拟书目材料”，extend_deadline=false；U005同意 | paused，collaboration_version=2 |
| C+3d／+3d+1h | U005申请resume，reason“模拟材料已补齐”，extend_deadline=false；U017同意 | in_progress，collaboration_version=3 |
| C+4d／+4d+1h | U017申请pause，reason“等待目录分类确认”，extend_deadline=false；U005同意 | paused，collaboration_version=4；阶段状态保留 |
| T049 C至C+2h | U001发布有偿¥50；U009申请并获选 | in_progress |
| T049 C+3d／+3d+1h | U009申请cancel，reason“范围调整，双方同意按已完成整理结算”，extend_deadline=false，cancellation_settlement_fen=2000；U001同意 | cancelled，协商金额¥20，collaboration_version=2 |
| T049 C+4d | U001确认付款，使用读取到的结算version | payer=true、payee=false |

T050按X执行，取消提案金额0，无结算确认动作。E时T045可由任一方提出恢复、另一方确认；T049由U009核对后确认收款。暂停和取消的成功均以另一方确认完成为准。

### 故事7：有偿完成后的独立结算（T038、T042、T044）

登录U006/U010查看T038，登录U002/U014查看T042，登录U004/U016查看T044；入口为任务详情中的线下结算面板。

T038完成S10最后阶段后，U006在C+5d确认付款（结算version 0→1）；U010在C+5d+1h确认收款（1→2），both_confirmed=true。T044同样两次确认，最终version=2。T042仅完成成果验收，不进行确认，双方均false、默认version=0。

E时T038双方可查看两次确认历史；T042双方可继续记录线下结算事实。有偿任务完成状态独立于结算确认，不把未确认付款展示为未完成任务。

### 故事8：满额、退出、FIFO递补（A011）

登录U003管理、U009退出、U018和U020查看本人报名；入口`/#/activities/{A011}`。B=E-9d，名额3。

| 时间 | 操作 | 获位／候补 |
|---|---|---|
| B／+10m／+20m | U001、U009、U016依次register | 3 registered |
| B+30m／+40m | U018、U020依次register | queue_sequence分别1、2 |
| B+1h | U009取消自己的报名 | U009 cancelled；同事务U018 promoted |

E时U020仍waitlisted，queue_sequence=2但waitlist_position=1；U018为registered。下一步U016若退出，应自动递补U020，不需要负责人手动转正。U003只能管理本人负责的活动名单。

### 故事9：拒绝、重申与时间推导未获名额（A018）

登录U002管理、U010/U012看本人历史，入口`/#/activities/{A018}`或“我的报名”；B=E-9d，名额2，S=E-3d-9h。

| 时间 | 操作 | 结果 |
|---|---|---|
| B／+2m | U010 register；U002 reject，reason“缺少讨论主题说明” | attempt1 rejected |
| B+10m | U012申请，说明“先申请，稍后补齐主题” | pending，负责人保留不处理 |
| B+20m／+22m | U014申请，U002 reject，reason“主题与本场讨论不符” | rejected |
| B+30m／+32m | U010重新申请，说明“已补充公共阅读空间主题”；U002 approve | attempt2 registered |
| B+40m／+42m | U016申请并通过 | registered，已满 |
| S及其后 | 仅推进时间，无写操作 | U012 DB pending，展示not_selected |

E时活动已结束，大厅不展示；U010可看两次尝试，U012不能再获审批名额。下一步只查看历史，不虚构“补签到”或学分补认定操作。

### 故事10：志愿换岗与岗位递补（V003）

登录U003管理，U009换岗，U012/U015查看结果，入口`/#/volunteers/{V003}`；每岗容量3，B=E-9d。

| 时间 | 操作 | 结果 |
|---|---|---|
| B／+10m／+20m | U009、U010、U011报名J1 | J1满 |
| B+30m／+40m | U012、U015报名J1 | J1队列1、2 |
| B／+10m | U016、U018报名J2 | J2余1 |
| B／+10m | U019、U020报名J3 | J3余1 |
| B+1h | U009取消J1报名 | J1中U012递补；U015候补第1 |
| B+1h+5m | U009报名J2 | 新attempt，J2满；旧J1 cancelled |

同用户同活动attempt按实际发生递增，不能跨岗位保留两条有效报名。E时活动open（J3尚有余位），不能因J1/J2满而展示整场full。下一步可由U020退出J3，或负责人查看U009两次报名历史。

### 故事11：参与登记、缺席、确认与更正（V016—V018、V020）

登录U001管理V017、U009/U011查看个人记录；另登录U004管理V020。入口为志愿详情名单及“我的志愿记录”。

| 时间 | 报名／操作 | 结果 |
|---|---|---|
| V017 F+10m | U001为U009登记participated、actual=120，version=0 | version1，待核验 |
| F+20m | U001确认120，输入version1 | version2，confirmed=120 |
| F+30m | U001更正actual=110，输入version2，reason“核对后扣除10分钟非服务时间” | version3，confirmed=null，旧120不再计入合计 |
| F+10m／+20m／+30m | U001为U011登记100、确认100、将确认改90（理由见时长表） | version3，confirmed=90，只计最新90 |
| V016 F+10m／+20m | U008登记U018 absent、0，并确认0，reason“未到场，不予计时” | confirmed=0，有明确缺席记录 |
| V020 S+50m | U004取消整场，reason“模拟场地临时关闭，提前结束” | 获位者activity_cancelled，最大分钟固定50 |
| V020 S+60m／+70m | U004登记U013实际40并确认40 | version2，confirmed40，未到原F也可因取消核验 |

其余时长按第5.3节执行。E时U009个人确认合计为0而非120；U011为90；U013为40；U010为120；U017为120；U007为110。下一步U001可给U009重新确认110，输入version3，成功后version4；U002可为V018的U012确认不超过100分钟。

### 故事12：发现补充、作者更新与撤回（D001、D030）

登录U021/U009/U014查看D001，登录U049/U020/U010查看D030，入口`/#/discoveries/{Dxxx}`；C分别按第6.1节计算。

| 时间 | 内容／操作 | 结果 |
|---|---|---|
| D001 C | U021发布，discovered_at=C-30m | unverified，version1 |
| C+1h／+2h | U009、U014分别comment补充桌位与现象 | 2条评论；作者收到2条消息，正文version仍1 |
| C+3h | U021 edit补充具体桌位，version=1 | version2，分类不变 |
| C+1d起每隔1h | U021依次state verified、reported、in_progress、resolved | version3→6，状态来源author_report |
| D030 C至C+3h | U049发布；U020、U010评论；U049编辑补充说明 | version2，2条评论 |
| D030 C+1d | U049 state expired，reason“模拟领取时段已结束” | version3 |
| D030 C+2d | U049 withdraw，version=3，reason“模拟地点说明有歧义，撤回原文” | version4，withdrawn_at已写入 |

E时D001默认列表隐藏，可按resolved筛选或从个人发布打开；D030仅作者能查看正文与版本，其他人详情只见撤回标记，评论列表不再公开。下一步U021可查看历史，或为其他未终止发现发表补充；D030不能继续编辑或评论。


## 8. 用户关系反向索引

下表仅计观察时点及此前已发生的业务关联。发布者列包括已发布但尚未开放的内容；参与列包括申请、撤回、候补、未获名额、评论等历史，不等同于到场或最终成功。任务被选定后的发布者审核、活动负责人的审核／核验隐含在发布关系内。

| 用户 | 发布的内容 | 参与／申请／评论的内容 | 不同主体关联数 |
|---|---|---|---:|
| U001 | T001、T015、T023、T033、T041、T049、V001、V009、V017、A001、A009、A017、D025 | A011 | 14 |
| U002 | T002、T016、T024、T034、T042、T050、V002、V010、V018、A002、A010、A018、D026 | A012 | 14 |
| U003 | T003、T017、T025、T035、T043、V003、V011、V019、A003、A011、A019、D027 | A013 | 13 |
| U004 | T004、T018、T026、T036、T044、V004、V012、V020、A004、A012、A020、D028 | A014 | 13 |
| U005 | T005、T019、T027、T037、T045、V005、V013、A005、A013、D021 | A015 | 11 |
| U006 | T006、T020、T028、T038、T046、V006、V014、A006、A014、D022 | A016 | 11 |
| U007 | T007、T021、T029、T031、T039、T047、V007、V015、A007、A015、D029 | V016 | 12 |
| U008 | T008、T022、T030、T032、T040、T048、V008、V016、A008、A016 | V017 | 11 |
| U009 | — | T002、T015、T037、T049、V003、V006、V009、V011、V013、V017、A009、A011、A017、D001、D011、D019 | 16 |
| U010 | — | T002、T007、T016、T038、T050、V003、V007、V010、V012、V018、A009、A013、A018、D002、D012、D021、D030 | 17 |
| U011 | — | T003、T005、T017、T031、T039、V003、V004、V006、V009、V013、V017、A009、A012、A017、D003、D013、D023 | 17 |
| U012 | — | T012、T018、T040、V003、V007、V010、V012、V018、A009、A013、A018、D004、D014、D024 | 14 |
| U013 | — | T019、T041、V004、V006、V011、V014、V020、A009、A012、A017、D005、D015、D025 | 13 |
| U014 | — | T020、T032、T042、V007、V010、V014、V020、A009、A014、A018、D001、D006、D016、D026 | 14 |
| U015 | — | T007、T021、T043、V003、V004、V008、V011、V015、A010、A012、A015、D003、D007、D017、D027 | 15 |
| U016 | — | T022、T044、V003、V010、V015、A010、A011、A016、A018、D005、D008、D018、D028 | 13 |
| U017 | — | T009、T023、T033、T045、V005、V008、V011、V016、V019、A010、A014、A019、D009、D013、D019、D025 | 16 |
| U018 | — | T024、T034、T046、V003、V010、V016、A010、A011、A015、A020、D010、D015、D020、D027 | 14 |
| U019 | — | T010、T025、T035、T047、V003、V005、V008、V011、V019、A010、A014、A019、D008、D011、D021、D029 | 16 |
| U020 | — | T009、T014、T024、T026、T036、T048、V003、V009、V010、V011、A010、A011、A016、A020、D010、D017、D022、D030 | 18 |
| U021 | T009、D001 | V004、V012、A004 | 5 |
| U022 | T010、D002 | V004、V012、A004 | 5 |
| U023 | T011、D003 | V004、V013、A004 | 5 |
| U024 | T012、D004 | V005、V013、A004 | 5 |
| U025 | T013、D005 | V005、V014、A005 | 5 |
| U026 | T014、D006 | V006、V014、A005 | 5 |
| U027 | D007 | T003、T027、V007、V015、A005 | 6 |
| U028 | D008 | T028、V008、V015、A005 | 5 |
| U029 | D009 | T029、V016、A006 | 4 |
| U030 | D010 | T030、V016、A006 | 4 |
| U031 | D011 | T005、V009、V017、A006 | 5 |
| U032 | D012 | V005、V017、A006 | 4 |
| U033 | D013 | V007、V018、A007 | 4 |
| U034 | D014 | V007、V018、A007 | 4 |
| U035 | D015 | V008、V019、A007 | 4 |
| U036 | D016 | V008、V019、A007 | 4 |
| U037 | D017 | V006、V020、A008 | 4 |
| U038 | D018 | V006、V020、A008 | 4 |
| U039 | D019 | V009、A008 | 3 |
| U040 | D020 | V009、A008 | 3 |
| U041 | — | T002 | 1 |
| U042 | — | A004 | 1 |
| U043 | — | T002 | 1 |
| U044 | — | A005 | 1 |
| U045 | — | V005 | 1 |
| U046 | D023 | — | 1 |
| U047 | D024 | — | 1 |
| U048 | — | V004 | 1 |
| U049 | D030 | — | 1 |
| U050 | — | A006 | 1 |


## 9. 现有接口映射与后续生成约束

本设计不新增公开API、数据库表、权限角色或业务状态。下表是后续执行器的接口映射，非本阶段开发任务；所有请求由真实登录会话确定当前用户，不能用请求体伪造操作者。

| 业务操作 | 现有服务入口 | HTTP入口 |
|---|---|---|
| 注册、登录、退出 | AuthService | POST `/api/auth/register`、`/api/auth/login`、`/api/auth/logout` |
| 任务发布、申请、接取 | TaskService.create_task/apply/claim | POST `/api/tasks`、`/api/tasks/{id}/applications`、`/api/tasks/{id}/claim` |
| 撤回申请、选定、下架 | TaskService.withdraw_application/accept_application/withdraw | POST `/api/applications/{id}/withdraw`、`/api/applications/{id}/accept`、`/api/tasks/{id}/withdraw` |
| 整项提交、验收 | TaskService.submit/review | POST `/api/tasks/{id}/submissions`、`/api/tasks/{id}/review` |
| 阶段计划与执行 | StageService.set_plan/start/submit/review | POST `/api/tasks/{id}/stages`、`/api/tasks/{id}/stages/{stage_id}/start`、`/submissions`、`/review` |
| 约定变更 | service.terms.changes.propose/decide | POST `/api/tasks/{task_id}/changes`、`/api/task-changes/{id}/review` |
| 协作暂停、恢复、取消 | service.terms.changes.propose_control/decide | POST `/api/tasks/{task_id}/collaboration-requests`、`/api/task-changes/{id}/review` |
| 线下结算确认 | service.terms.confirm | POST `/api/tasks/{task_id}/settlement/confirmation` |
| 综素发布、报名、审核、退出、整场取消 | ActivityService.create/register/review/cancel_registration/cancel_activity | POST `/api/activities`、`/api/activities/{id}/registrations`、`/api/registrations/{id}/review`、`/api/registrations/{id}/cancel`、`/api/activities/{id}/cancel` |
| 志愿发布、报名、审核、退出、整场取消 | VolunteerService对应方法 | POST `/api/volunteers`、`/api/volunteer-jobs/{id}/registrations`、`/api/volunteer-registrations/{id}/review`、`/api/volunteer-registrations/{id}/cancel`、`/api/volunteers/{id}/cancel` |
| 参与登记、分钟核验 | VolunteerService.update_record | POST `/api/volunteer-registrations/{id}/participation`、`/api/volunteer-registrations/{id}/hours` |
| 发现发布、编辑、状态、撤回、评论 | DiscoveryService.create/edit/state/comment | POST `/api/discoveries`、PATCH `/api/discoveries/{id}`、POST `/api/discoveries/{id}/status`、`/withdraw`、`/comments` |
| 站内消息查询与已读 | NotificationService.list/read | GET `/api/me/messages`；POST `/api/me/messages/read-all`（through_id=max_id）、`/api/me/messages/{id}/read` |

### 9.1 操作与版本规则

- 后续生成应先建立50个账号与ID映射，再将全部发布、申请、审批、成果、评论和登记操作按绝对时间排序执行。同一时刻依照“内容类型T→A→V→D、编号、岗位编号、表格操作顺序”稳定排序；取消释放名额和自动递补由服务在同一事务处理。
- 每次动作前读取当前对象与版本；阶段动作使用阶段version，整项成果使用collaboration_version，约定提案使用terms_version对应的version，协作控制另传collaboration_version，审批传提案自身version。不要把三种版本混用。
- 生成器通过上下文隔离的业务时钟统一回放期间的操作、历史及消息时间；阶段计划／验收使用任务服务时钟。演示HTTP请求沿用该时钟，登录会话有效期仍按真实时钟计算。不能只平移deadline而保留错误的操作时间。
- 观察状态必须在E读取，不能在真实运行时钟下比较固定2026年样本。未来动态演示使用单独副本或整体平移时间，维持时间边界与操作先后；历史回放与观看未来演示是两个阶段。
- 数据读取遵守现有可见性：本人查看申请说明、报名结果与服务记录；负责人查看自己内容的名单及核验材料；普通公众不能读取全量参与者私有数据。设计文档是本机测试规格，不作为平台公共名单。

### 9.2 消息与首页

不直接手写消息条目。后续由业务操作正常触发notifications；同一event_key重试不得重复消息。保留数据库已有的业务事件、提交记录、约定版本、志愿记录版本和发现版本，不把本文每个步骤都伪造成一条通用审计日志。

| 触发情形 | 预期消息 |
|---|---|
| 任务申请、撤回、直接接取 | 发布者收到相应业务消息 |
| 任务选定或下架 | 受影响申请人收到结果消息 |
| 成果提交、退回、通过及阶段动作 | 对方收到相应协作消息 |
| 变更或控制申请、审批结果 | 对方收到提案／结果消息 |
| 有偿完成、取消结算就绪及单方结算确认 | 按现有服务规则提醒双方或对方 |
| 活动审核申请 | 申请者收到待审核消息，负责人收到待审核申请消息 |
| 活动直接报名、审核结果、候补转正 | 申请者收到自身结果消息；不额外给负责人造直接报名提醒 |
| 参与者取消报名 | 负责人收到退出消息；不额外给退出者造确认消息 |
| 整场取消 | 受影响的参与者按实际业务规则收到取消消息 |
| 志愿参与登记、分钟确认及更正 | 本人收到记录变化消息；旧确认失效有对应提醒 |
| 他人评论校园发现 | 发现作者收到新评论消息 |
| 时间经过、自己评论、发现编辑或状态更新 | 不额外构造消息 |

已读交互仅安排8个组织用户：在E-6h分别读取自己的消息页并以当次max_id标记此前消息已读；其他用户不做已读操作。此动作不增加主体内容数。E-2h的T026新提案会给U004留下未读消息，E-10m的V014/V015登记会给对应参与者留下未读消息。引航员读取数据不标记消息已读。

首页预期：U004有T026待处理提案；U003有T003待选申请及V003名单管理入口；U014有T020阶段补充事项；U001有V017-U009待重新核验；U002有V018-U012待核验。只核对当前首页实际支持的待办项；名单管理入口不冒充必须出现的自动待办。

### 9.3 查阅与继续体验入口

| 目的 | 网页入口 | 示例账号与内容 |
|---|---|---|
| 未接取任务与申请选择 | `/#/tasks`、`/#/tasks/{id}` | U002管理T002；U043可接T004 |
| 协作、阶段、变更、结算 | `/#/mine`、任务详情 | U014处理T020；U004审批T026；U009核对T049收款 |
| 综素本人结果／负责人历史 | `/#/mine/registrations`、`/#/mine/activities` | U010查A018重申；U003管理A011 |
| 志愿报名／负责人历史 | `/#/mine/registrations?type=volunteer`、`/#/mine/activities?type=volunteer` | U009查V003换岗；U004查V020取消 |
| 参与和确认小时 | `/#/mine/volunteer-records` | U009看到旧120失效；U011看到最新90 |
| 发现终态与撤回 | `/#/discoveries`按状态筛选、`/#/mine/discoveries` | U021查D001历史；U049查D030原文 |
| 站内消息与个人概览 | `/#/messages`、`/#/home` | U004查看T026新提案消息 |

## 10. 检查清单与验收依据

### 10.1 设计文档静态检查

- [x] 50个U、50个T、20个V、20个A、30个D，编号连续且不重复；12条故事各出现一次。
- [x] 分类、奖励、接取方式、状态、活动标签、主题、岗位数量符合第1.1节。
- [x] 各活动负责人不出现在自己的报名链；任务发布者与接取者不同。
- [x] 每个账号有至少一项观察时点前的业务行为；U041—U050各关联1条主体内容。
- [x] 高频组平均关联15.25条不同主体内容，普通组平均4.40条，低频组平均1.00条；此为设计关系数，不是虚构的平台埋点统计。
- [x] 反向索引包含T024中U020未获选申请；不计故事1中U043未来接取T004的建议。
- [x] 按字段模板构造的50个注册输入、120条主体内容输入及48个岗位通过现有Pydantic模型校验；活动窗口、阶段截止、发现分类状态及已获名额用户的跨活动时段检查通过。
- [x] 时长表最新有效确认合计870分钟（14.5小时）；个人合计与故事11一致，已失效的旧确认不重复累加。

### 10.2 后续生成后的业务验收（本阶段尚未执行）

- [ ] 使用Pydantic现有输入模型校验全部展开字段，活动报名窗口与岗位时段满足现有限制；发布发生时活动尚未开始。
- [ ] 在E核对任务主状态分布；T009/T010/T011已截止未接取，T012/T013为下架，T025/T029的is_overdue=true；T047暂停且截止已过，is_overdue=false。
- [ ] S1—S12按顺序推进，不能跳过未确认阶段；S6阶段2被退回，S7阶段2待验收，S8阶段1待验收，S9/S10全部确认。
- [ ] A011队列顺序与当前位置不同但正确；A012/A013满额；A018保留两次申请，U012只在读取时显示not_selected。
- [ ] V003同一用户只有一条有效报名，旧岗位保留cancelled；J3余1，整场open；V009—V011所有岗位满额且各有候补。
- [ ] V014/V015尚未结束，登记后仍不能核验；V016—V018已结束；V019无核验资格，V020取消前获位者保留资格且分钟上限50。
- [ ] V017-U009最新确认null，旧120不计；U011最新90；零分钟确认有理由；confirmed_minutes始终不超过actual_minutes与已发生服务上限。
- [ ] 两类活动结束不额外生成签到或认定记录，学校正式分钟数始终null。
- [ ] D001版本6且状态resolved；D030版本4并撤回；非作者不再取得D030正文与评论，其他发现状态均属于各自分类。
- [ ] 业务消息仅由现有触发器生成，组织用户已读操作只影响自己当时可见的消息；不存在邮件、私聊、定时提醒或模型访问记录伪造。
- [ ] 重启后数据持久，全部设计键可映射真实ID；各账号的个人数据权限正确，默认大厅隐藏的历史从对应个人入口仍可访问。

第一版的成功标准是：文档中每一项内容都能找到发布者、具体参与者、可执行的操作链和E时结果；生成器不额外发明用户关系、名额安排或故事分支。每批实际回放、真实登录及HTTP验收结果见生成目录的acceptance.md/json；可视化多用户操作和真实Agent评测分别开展。
