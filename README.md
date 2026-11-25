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

每次开始先运行 `python -X utf8 scripts/workspace.py refresh`，打开实例 memory/CURRENT_STATE.md。当前方向、实际检索范围、简历版本、企业岗位申请状态、笔面缺口和下一步在同一页显示。现有用户与新用户共用同一入口；方法和状态职责见 [工作闭环](docs/工作闭环.md)。

每次工作结束先更新原台账或材料，再用 workspace.py close 更新现行决定。材料修改后未复审、范围与方向不一致、提交缺回执会直接提示，不能靠逐日文档猜进度。

## 目录组织

代码、方法、空模板与个人工作线在同一个项目根目录。harness 是工作机制的名称，不再是包住另一套工程的目录。

```text
offerloop/
├── AGENTS.md / README.md
├── scripts/  docs/  config/  templates/  tests/  skills/
├── 内容线/  笔面线/
├── memory/
└── .local/  data/  offerloop.local.json
```

四条线是工作职责，不对应四套目录与规则。内容线、笔面线和个人状态由初始化生成并被 Git 忽略；行业和投递直接使用 docs/ 中的方法、统一状态与台账，不再生成只有路由作用的一级目录。

## 组织方式

| 部分 | 持续职责 |
| --- | --- |
| AGENTS.md / README.md | 助手约定与用户入口 |
| docs/ | 可复用筛选、背调、材料与训练方法，工具说明 |
| templates/workspace/ | 材料、笔面入口与接续记忆的空模板，初始化时生成私有工作文件 |
| config/ | 通用平台适配与 example 模板 |
| scripts/ / tests/ / skills/ | 执行代码、验证和可选训练工作流 |
| .local/profile/ | 唯一个人条件与偏好来源，四条线共同引用 |
| .local/config/ | 当前检索范围、执行策略与选用的面经研究配置 |
| 内容线/ | 现用简历、项目卡及仍待处理的评审批注，通用方法放 docs/ |
| 笔面线/ | 真实题源、原始作答和复验材料，缺口状态只维护训练台账 |
| memory/ | workspace.json 维护现行决定与材料状态；CURRENT_STATE.md 自动汇总当前工作 |
| data/ | 本地台账、真实回执、去重和恢复状态 |

个人目录、data 和 offerloop.local.json 均被 Git 忽略。相对路径以实例配置所在目录为基准。初始化只补缺失文件，重复运行不覆盖资料。方法就地更新，一次性研究提炼后清理，不按天生成报告或历史目录。

## 工作如何推进

个人条件 → 行业与岗位准入 → 原 JD 和 APP-ID → 简历与项目证据 → 本地训练与实际申请 → 招聘反馈调整方向。

四条线通过共同档案、岗位 ID 和现行产物连接。没有默认职业路线，非技术岗位也可使用。方向不确定可先探索，不因表格未填满而停工；确认范围后再启动结构化检索。投递、联系和上传均需相应授权，初始化不会触发外发。

方法入口：[行业与岗位](docs/岗位筛选规则.md) · [企业背调](docs/企业背调方法论.md) · [材料与训练](docs/材料与训练.md) · [执行手册](docs/RUNBOOK.md)。

## 接续和换设备

新会话先读 AGENTS 和实例 memory/CURRENT_STATE.md，再打开该任务的现用材料，不需要旧会话记录。换设备只拉代码可开始新档案；继续原用户必须另行私下恢复 offerloop.local.json、.local、内容线、笔面线、memory 和配置指向的台账目录。旧实例另有仍被引用的材料时一并恢复。SQLite 做一致性备份或停写后复制，浏览器和飞书重新认证。不要把个人资料提交到公开 Git。

同机多用户用 `setup.py --workspace <独立目录>`，之后设置 OFFERLOOP_LOCAL 指向该目录的配置。仓库根目录就是工作根目录，无需额外嵌套 harness 文件夹。

## 可选工具及边界

招聘页面工具需要 Node.js 22+ 和 Chrome，见 [浏览器接入](docs/DSH-上手.md)。页面选择器必须按当前平台重新核实。旧在线简历 profile.py 仍有特定格式约束，不属于新用户建档流程；外部自动提交能力有额外限制，不能视为所有岗位均已适配。

飞书用于进度、跟进、规则摘要和阶段复盘。配置运行目录 feishu/connection.json 后，以 `python -X utf8 scripts/feishu_base.py --sync` 预览，明确授权后才加 --apply 并读回。训练原文留本地，本地 SQLite 承担防重和恢复，云端看板不代替完整台账。

验证：`python -X utf8 -m unittest discover -s tests -p "test_*.py"`。其中全新用户回放验证空目录、对话事实写入、接续、多用户隔离和重复初始化；不把离线测试当作真实招聘成效。许可见 [LICENSE](LICENSE)。
