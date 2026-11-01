# OfferLoop

**OfferLoop —— 面向 DeepSeek Harness（DSH）的 AI 求职执行框架，把求职流水线做成可 dry-run、可复用的开源工具。**

它把「发现岗位 → 筛选 → 背调 → 投递 → 跟进」这一串本来靠手工重复的活，收敛成一组固定命令 + 一份配置。默认全部 dry-run：不真实投递、不真实打招呼，先把链路跑通、把岗位看明白，再由你本人决定最后一下。

## 特性

- **DSH 智能体驱动**：命令是固定的，DSH 智能体（如 deepseek-flash）只需按 `chain.py <步骤>` 依次执行，不需要理解任何平台的 DOM 与交互细节。
- **三通用能力 + 平台适配器**：`greet`（打招呼）/ `apply`（投递）/ `update_resume`（更新在线简历），平台差异全部封装在 `config/`。
- **完整生命周期**：`chain.py` 提供 `discover → import → screen → check → prepare → ready → submit → followup`，每步可单跑，`run` 可一次串起。
- **数据一次定义、多平台复用**：姓名、学历、履历、简历文件只在 `config/投递数据.json` 写一次，各平台共用。
- **分阶段背调**：初筛只做 C1–C5 + J1–J5（轻量检查）；跨过简历沟通关、进入笔试/面试邀约后才做全量三层 × 七维（含 C6 风险、C7 岗位真实性）。背调投入与招聘意愿信号成正比。
- **安全默认**：dry-run 优先；真实投递只允许外包/派遣类岗位，且需你显式授权；正编岗与「在考虑范围」岗只登记不投。
- **一套话术 + 一套简历**：批量招聘岗不逐岗打磨，只有核心高匹配岗才微调 1–2 句。

## 支持平台

| 平台 | 已具备的能力 | 状态 |
|---|---|---|
| BOSS直聘 | 发现岗位（列表提取）、打招呼、投递（定位 + 抓回执） | 真实投递已验证跑通 |
| 智联招聘 | 发现岗位（含 SSR 列表）、投递（定位 + 抓回执）、在线简历（分节编辑） | 真实投递已验证跑通 |
| 牛客 | 岗位正文解析（`scripts/nowcoder_parse.py`，服务端渲染页可直接取全文） | 解析可用 |
| 企业官网 | 登录 / 岗位列表 / 投递选择器适配（`config/companies.json`，一家一个 key） | 适配器已配，按需增删 |

**新增平台只需加配置，不改主流程**：
1. `config/platforms.json` 加搜索 URL、岗位卡片与提交按钮选择器；
2. `config/harness.json` 给 `greet` / `apply` / `update_resume` 加该平台适配条目；
3. 需要填表时在 `config/field_mapping.json` 加字段映射；
4. 企业官网直接往 `config/companies.json` 加一个 key；
5. 用 dry-run 验证（`chain.py submit` 不带 `--execute` 时只定位、不点击）。

## 怎么跑起来（架构）

```
人 / DSH 智能体
      │  固定命令（chain.py / harness.py）
      ▼
scripts/chain.py              发现 / 入库 / 筛选 / 清单 / 投递 / 跟进（默认 dry-run）
      │  node 调用
      ▼
scripts/browser_cdp.js        CDP 客户端（Node 22 内置 WebSocket，无额外依赖）
      │  ws://127.0.0.1:9222
      ▼
宿主机 Chrome（--remote-debugging-port=9222，专用 profile，登录态持久）
      ▼
BOSS直聘 / 智联招聘 / 企业官网
```

两个关键设计：

- **浏览器必须在宿主机跑，框架只做驱动。** 沙箱里起不了 Chromium，也不需要：Chrome 由你在桌面双击 `scripts/browser_launch.cmd` 启动，脚本通过 CDP 连接它。
- **登录态由 profile 持久化。** 登录一次，之后同一 profile 复用；验证码、新协议这类还是要你本人处理。

所以同一套框架，上层可以是 DSH 智能体，也可以是你手敲命令，行为完全一致。

## 快速开始

### 1. 前置条件

- Python **3.11+**（脚本只用标准库，无需 `pip install`）
- Node.js **22+**（`browser_cdp.js` 用内置 WebSocket）
- Google Chrome（用于 CDP 驱动）
- 可选：DeepSeek Harness（DSH）环境 —— 想用智能体替你执行时才需要

### 2. 获取仓库

```bash
git clone https://github.com/yujinandyanhaoyang/offerloop.git
cd offerloop
```

### 3. 复制配置模板为真实配置

```powershell
Copy-Item config\投递数据.example.json   config\投递数据.json
Copy-Item config\执行策略.example.json   config\执行策略.json
Copy-Item config\当前检索范围.example.json config\当前检索范围.json
```

真实配置文件已写进 `.gitignore`，不会被误提交。

### 4. 填个人信息

- `config/投递数据.json`：姓名、手机、邮箱、学历、履历、期望城市 —— **只填这一次**，所有平台复用。
- `config/当前检索范围.json`：要投的城市 × 岗位族（`cells[].industry` / `city` / `role_terms`）。
- `config/执行策略.json`：批次上限、冷却、`external_actions_enabled`（先保持 `false`）。

### 5. 可选：放简历

把简历放到 `config/resume.md` 或 `config/resume.pdf`（同样已 gitignore）。没有也能先跑 dry-run。

### 6. 跑一次 dry-run

```powershell
python -X utf8 scripts/chain.py status   # 一眼看现状：台账 + 待办清单 + 环境就绪（只读）
python -X utf8 scripts/chain.py run      # 串起 发现→入库→筛选→清单→投递计划（全 dry-run）
```

`status` 不需要浏览器就能跑；`run` 里的 `discover` 需要你先启动带调试端口的 Chrome，并让已登录的标签停在目标平台搜索结果页。

### 7. 真实投递前必读

第一次真实投递之前，请按 [docs/DSH-上手.md](docs/DSH-上手.md) 走一遍检查清单：登录与验证码归你、敏感字段不采集、先小范围试投外包/派遣类岗位、遵守平台频率限制。**默认不真实投递**，开不开这个口子由你本人决定。

## 模型建议

| 模型 | 角色 | 理由 |
|---|---|---|
| deepseek-flash | 按固定命令执行 | 框架已把平台选择器、表单映射、回执判定都封在配置里，flash 不需要理解平台细节，照 `chain.py` 步骤跑即可，便宜且快 |
| deepseek-v4-pro | 决策与审查 | 岗位取舍、背调结论、话术微调、跟进回复这类判断，交给更强的模型，并由你本人确认 |

一句话：**flash 干活，pro 拿主意，人做决定。**

## 目录

```
offerloop/
├── README.md
├── LICENSE
├── CONTRIBUTING.md
├── .gitignore
├── scripts/        # 代码（chain.py / harness.py / pipeline.py / browser_cdp.js ...）
├── config/         # 配置（*.example.json 模板；真实配置 gitignored）
├── docs/           # 上手文档、能力手册、海投链路、RUNBOOK、岗位筛选规则、通用话术
├── tests/          # 测试
└── data/           # 运行时数据（台账 / 回执 / 投递清单，gitignored）
```

## 配置模板

| 模板 | 复制为 | 作用 |
|---|---|---|
| `config/投递数据.example.json` | `config/投递数据.json` | 个人投递数据（定义一次，多平台复用） |
| `config/执行策略.example.json` | `config/执行策略.json` | 筛选 / 背调 / 执行策略与边界 |
| `config/当前检索范围.example.json` | `config/当前检索范围.json` | 岗位族 × 城市的检索范围 |

适配器配置（`config/harness.json` / `platforms.json` / `companies.json` / `field_mapping.json`）是通用的，可直接用，也可按平台维护。

## 环境变量

| 变量 | 作用 | 默认值 |
|---|---|---|
| `OFFERLOOP_HOME` | 数据目录（台账 / 证据 / 回执 / 投递清单） | `<repo>/data` |
| `OFFERLOOP_CONFIG` | 项目配置目录（投递数据 / 执行策略 / 检索范围） | `<repo>/config` |
| `OFFERLOOP_ADAPTERS` | 平台适配配置目录 | 同 `OFFERLOOP_CONFIG` |
| `OFFERLOOP_OUTSOURCING_MARKERS` | 覆盖外包岗判定关键词（逗号分隔） | `外包,派遣,劳务,od,od外包` |

也可以把路径写进 `offerloop.local.json`（放在仓库根或其上级目录），优先级：环境变量 > `offerloop.local.json` > 默认值。

## 边界

- **人工保留项**：登录、验证码、新协议、接受 offer、离职、迁居 —— 由本人处理，程序不代做。
- **敏感字段不采集**：身份证号、护照、人脸识别、生物识别 —— 一律不采集、不填写，也不写进台账、日志或截图。
- **真实投递只限外包/派遣类岗位**：正编岗与「在考虑范围」岗只登记、不真实投递。判定是启发式（关键词匹配），最终以实际劳动主体为准。
- **默认 dry-run**：`submit` / `apply` 不带 `--execute` 只定位按钮、不点击；回执状态为未知时先对账，不重投。
- **频率与平台规则**：请自行遵守目标平台的用户协议与访问频率限制，不用于批量骚扰、爬取或自动登录。

## 文档导航

| 文档 | 内容 |
|---|---|
| [docs/DSH-上手.md](docs/DSH-上手.md) | **新人从这里开始**：从零到首次 dry-run 全闭环，含配置逐项说明与真实投递前检查清单 |
| [docs/能力手册.md](docs/能力手册.md) | 三个通用能力、命令速查、适配状态与给模型的最小操作指引 |
| [docs/RUNBOOK.md](docs/RUNBOOK.md) | 执行机制、流程与口径：发现 / 研究 / 材料 / 投递 / 跟进各阶段怎么跑、什么时候停 |
| [docs/海投链路.md](docs/海投链路.md) | 五步主链路与投递闭环的命令、产出与前置后置 |
| [docs/岗位筛选规则.md](docs/岗位筛选规则.md) | 公司与岗位过滤器（C1–C5 / J1–J5、分阶段取证） |
| [docs/通用打招呼话术.md](docs/通用打招呼话术.md) | 一套可复用的话术模板与使用规则 |

## 许可

MIT，见 [LICENSE](LICENSE)。

Copyright (c) 2026 OfferLoop contributors。可自由使用、修改、分发（含商业用途），前提是保留版权与许可声明。
