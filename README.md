# OfferLoop

通过对话建立个人档案，持续推进方向研究、材料准备、本地笔面和投递跟进。通用方法和工具入 Git，个人资料在私有实例中。可选用飞书查看进度与复盘。

## 从零开始

准备 Git 和 Python 3.11+，克隆本仓库。在能读写本地文件、执行命令的 AI 助手中打开仓库目录，直接说：

> 请按 AGENTS.md 初始化 OfferLoop。我是新用户，请通过对话了解我的背景和求职需求，建立档案，然后开始我当前最需要的工作。

助手将创建个人档案、当前状态和材料目录，分几轮询问必要信息，不要求手动填 JSON，不要求先配置飞书或浏览器。联网研究需要助手具备搜索能力，未接入时仍可先整理个人证据和材料。初始化脚本自身不提供聊天模型。

手动检查也可运行：

```powershell
python -X utf8 scripts/setup.py
python -X utf8 scripts/onboard.py status
python -X utf8 scripts/chain.py status
python -X utf8 scripts/interview_drill.py status
```

零岗位、零训练是正常新实例。建档和接续流程见 [建档与接续](docs/建档与接续.md)。

## 日常使用

每次开始先运行 `python -X utf8 scripts/workspace.py refresh`，打开实例 memory/CURRENT_STATE.md（默认 workspace/memory/CURRENT_STATE.md）。当前方向、实际检索范围、简历版本、企业岗位申请状态、笔面缺口和下一步在同一页显示。现有用户与新用户共用同一入口；方法和状态职责见 [工作闭环](docs/工作闭环.md)。

每次工作结束先更新原台账或材料，再用 workspace.py close 更新现行决定。材料修改后未复审、范围与方向不一致、提交缺回执会直接提示，不能靠逐日文档猜进度。

## 目录组织

公共框架只保留一套；个人工作集中在 `workspace/`。harness 是工作机制，不再单独套一层目录。

```text
offerloop/
├── AGENTS.md / README.md
├── docs/                 通用方法与操作说明
│   └── 行业线/           研究渠道、筛选与企业背调
├── scripts/              投递、材料、训练与状态工具
│   ├── config/           平台适配及空配置示例
│   └── templates/        初始化使用的空模板
├── skills/               可复用的助手工作流
├── tests/                框架验证
└── workspace/            当前用户的私有实例，不入 Git
    ├── offerloop.local.json
    ├── profile/          唯一个人档案：条件、偏好与限制
    ├── config/           本人的检索范围与执行配置
    ├── 内容线/           现用简历、项目卡及待处理评审
    ├── 笔面线/           真实题源、原始作答与复验材料
    ├── memory/           现行决定与自动生成的当前工作页
    ├── data/             台账、回执、去重与恢复状态
    └── runtime/          按需生成的浏览器会话与本机认证
```

四条线是工作职责。行业研究方法直接使用 docs/行业线；投递能力直接使用 scripts、scripts/config 和执行手册。个人的方向取舍进入 memory，实际检索范围进入 config，具体岗位和进度进入 data 的台账。模板只用于初始化，日常不维护第二份个人文件。

实例内相对路径以 offerloop.local.json 所在目录为基准。初始化只补缺失文件，重复运行不覆盖资料。一次性研究用完即提炼进现行文档并清理，不另建日期报告、历史目录或 .local 缓存库。真实回执和未完成动作按恢复用途保留。

## 行业线与投递线在哪里

行业线的公共入口是 [行业研究方法](docs/行业线/行业研究方法.md)，包括查什么渠道和报告、怎样辨别上行下行、哪些证据会推翻判断，再进入筛选与企业背调。可复用行业认识可以公开维护，需保留来源、适用期间与失效条件；不随每位用户重新建一份方法库。

投递能力由 scripts/ 下的 chain、pipeline、execution 等工具和 scripts/config/ 适配配置实现，使用说明在 [执行手册](docs/RUNBOOK.md)。skills/ 只承载已实现、确有复用需要的助手工作流，不能以增加空技能代替工具能力；当前公共技能为本地笔面训练。

个人意向、城市和用工偏好进入个人档案；针对本人的行业取舍与改判条件进入当前状态；具体 JD、岗位分析、申请和反馈进入台账。公共方法负责“如何研究和执行”，个人实例负责“这个人选择什么、目前推进到哪里”。

## 工作如何推进

个人条件 → 行业与岗位准入 → 原 JD 和 APP-ID → 简历与项目证据 → 本地训练与实际申请 → 招聘反馈调整方向。

四条线通过共同档案、岗位 ID 和现行产物连接。没有默认职业路线，非技术岗位也可使用。方向不确定可先探索，不因表格未填满而停工；确认范围后再启动结构化检索。投递、联系和上传均需相应授权，初始化不会触发外发。

方法入口：[行业与岗位](docs/行业线/岗位筛选规则.md) · [企业背调](docs/行业线/企业背调方法论.md) · [材料与训练](docs/材料与训练.md) · [执行手册](docs/RUNBOOK.md)。

## 接续和换设备

新会话先读 AGENTS 和实例 memory/CURRENT_STATE.md（默认 workspace/memory/CURRENT_STATE.md），再打开该任务的现用材料，不需要旧会话记录。换设备只拉代码可开始新档案；继续原用户需通过私有渠道恢复整个 workspace，再运行 setup.py 和 workspace.py refresh。SQLite 做一致性备份或停写后复制；浏览器和加密凭据可能绑定设备，需要重新认证。不要把个人资料提交到公开 Git。

同机多用户用 `setup.py --workspace <独立目录>`，之后设置 OFFERLOOP_LOCAL 指向该目录的配置。仓库根目录就是工作根目录，无需额外嵌套 harness 文件夹。

## 可选工具及边界

招聘页面工具需要 Node.js 22+ 和 Chrome，见 [浏览器接入](docs/DSH-上手.md)。页面选择器必须按当前平台重新核实。旧在线简历 profile.py 仍有特定格式约束，不属于新用户建档流程；外部自动提交能力有额外限制，不能视为所有岗位均已适配。

飞书用于进度、跟进、规则摘要和阶段复盘。配置运行目录 feishu/connection.json 后，以 `python -X utf8 scripts/feishu_base.py --sync` 预览，明确授权后才加 --apply 并读回。训练原文留本地，本地 SQLite 承担防重和恢复，云端看板不代替完整台账。

验证：`python -X utf8 -m unittest discover -s tests -p "test_*.py"`。其中全新用户回放验证空目录、对话事实写入、接续、多用户隔离和重复初始化；不把离线测试当作真实招聘成效。许可见 [LICENSE](LICENSE)。
