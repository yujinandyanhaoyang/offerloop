# DSH 上手：从零跑通 OfferLoop

面向第一次接触 DeepSeek Harness（DSH）和 OfferLoop 的人。读完并按顺序做完，你能在 30 分钟内完成一次完整的 dry-run：环境就绪、配置填好、链路跑通、看到一份属于你自己的投递清单 —— 全程不真实投递、不真实打招呼。

> 所有命令都以**仓库根目录**为工作目录。Windows 下统一用 `python -X utf8`，避免中文路径/输出乱码。

## 0 适用对象与预期

**适合你，如果**：你在秋招或社招，手上有 DSH 环境，想让 AI 把「找岗位、筛岗位、整理投递清单、跟进」这些重复劳动接过去，但**不愿意**把账号、验证码和最终决策交出去。

**30 分钟后的预期产出**：

| 产出 | 位置 |
|---|---|
| 一份可用的个人配置（只填一次，多平台复用） | `config/投递数据.json` 等 3 个文件 |
| 一份本地台账（SQLite） | `data/ledger.sqlite3` |
| 一份投递清单 | `data/投递清单.md` |
| 一条跑通的 dry-run 证据链 | 终端输出 + 上述文件 |

**不会有的东西**：不会替你登录、不会识别验证码、不会自动点「投递」、不会替你接受 offer。这些永远由你本人做。

## 1 环境准备

### 1.1 DeepSeek Harness（DSH）环境

如果你打算让智能体替你敲命令，需要先有可用的 DeepSeek Harness（DSH）环境。没有也能用 —— 本框架所有能力都能由你手工执行同样的命令。

### 1.2 Python 3.11+

```powershell
python --version
```

脚本只用 Python 标准库，**不需要** `pip install` 任何东西。若 `python` 不是 3.11+，换 `py -3.11` 或把新版加进 PATH。

### 1.3 Node.js 22+

```powershell
node --version
```

要求 22+：`scripts/browser_cdp.js` 用的是 Node 内置 WebSocket，没有 `node_modules`、没有 `npm install`。

### 1.4 Chrome 与 CDP 端口

框架不自己启动浏览器，而是驱动你在**宿主机**上开的一个 Chrome。仓库提供了启动脚本：

```powershell
scripts\browser_launch.cmd
```

在资源管理器里**双击这个文件**，不要点网页里的链接。它做三件事：

1. 用一个**专用 profile** 启动 Chrome，带 `--remote-debugging-port=9222`；
2. profile 路径默认按 `<仓库根>\..\.local\browser-profile` 计算，登录态存在这里，所以登录一次之后下次还在；
3. 弹出一个新窗口，等你去登录。

脚本里写死了 Chrome 路径（`C:\Program Files\Google\Chrome\Application\chrome.exe`）。装到别处就编辑这个文件里的 `CHROME`；想换 profile 位置就改 `PROFILE`。

**验证端口是否真的开了**：在同一个窗口访问

```
http://127.0.0.1:9222/json/version
```

返回一段 JSON（含 `Browser` 字段）就说明 CDP 通了。

**登录归你**：在那个窗口里自己登录 BOSS直聘 / 智联招聘。短信验证码、图形验证码、新协议勾选，都由你本人处理 —— 框架不采集、不代填、不做验证码识别。

> 一句话：**Chrome 在桌面上跑，框架只通过 9222 端口驱动它。** 这就是为什么沙箱里不需要、也不应该起 Chromium。

## 2 获取仓库

```bash
git clone https://github.com/yujinandyanhaoyang/offerloop.git
cd offerloop
```

后续所有命令都在这个目录下执行。

## 3 配置

### 3.1 复制模板

```powershell
Copy-Item config\投递数据.example.json     config\投递数据.json
Copy-Item config\执行策略.example.json     config\执行策略.json
Copy-Item config\当前检索范围.example.json config\当前检索范围.json
```

这 3 个真实配置文件都在 `.gitignore` 里（`config/投递数据.json`、`config/执行策略.json`、`config/当前检索范围.json`），**不会误提交**。改配置只改你自己的真实文件，不要改 `*.example.json` 模板（模板是给别人复制的）。

适配器配置（`harness.json` / `platforms.json` / `companies.json` / `field_mapping.json`）是通用的，第一次不用动。

### 3.2 `config/投递数据.json` —— 个人投递数据（只定义一次）

| 字段 | 说明 |
|---|---|
| `name` / `gender` / `birth` | 基本信息，投表时作为唯一来源 |
| `phone` / `email` | 联系方式；`phone_policy: follow_login` 表示优先沿用平台登录手机号 |
| `education` | 学校 / 专业 / 学历 / 起止年份 |
| `work_years` | 工作年限 |
| `city` / `expected_cities` | 期望城市；与检索范围里的城市配套 |
| `work_experience[]` | 履历，每段含公司 / 职位 / 起止时间 |
| `resume_pdf` / `resume_photo` | 简历与照片文件名（相对 `config/`） |
| `skip_fields` | **保持默认**：身份证号、护照、人脸识别、生物识别 —— 永不采集 |
| `notes` | 给自己看的提醒 |

**为什么只填一次**：BOSS、智联、企业官网的表单字段各不相同，但数据源只有这一份。平台差异由 `field_mapping.json` 的选择器映射解决，你不需要为每个平台复制一遍个人信息。

**不要写进去的东西**：证件号码、证件影像、人脸/生物特征、账号密码、验证码、支付信息。

### 3.3 `config/执行策略.json` —— 策略与边界

| 字段 | 含义 | 第一次建议 |
|---|---|---|
| `ready_buffer` | 备好材料的岗位保持几份 | `3` |
| `batch_max_jobs` / `batch_max_minutes` | 单批上限（岗位数 / 分钟） | `3` / `15` |
| `search_window_months` | 检索回溯窗口（月） | `3` |
| `discovery_interval_hours` | 同一检索单元的最短重查间隔 | `24` |
| `empty_twice_cooldown_hours` | 连续两次零新增后的冷却 | `72` |
| `external_actions_enabled` | **真实外发总开关** | **保持 `false`** |
| `screening_filter` | 公司 C1–C5 / 岗位 J1–J5 检查项、背调分层规则 | 沿用默认 |

`screening_filter.backcheck_staging` 决定背调深度：初筛只做轻量项，跨过简历沟通关、进入笔试/面试邀约后才做全量（含 C6 风险、C7 岗位真实性）。

### 3.4 `config/当前检索范围.json` —— 找什么城市、什么岗位

`cells[]` 里每一项是一个「行业 × 城市 × 岗位词」检索单元：

```json
{
  "id": "CELL-1",
  "industry_id": "AGENT",
  "industry": "业务流程型Agent应用研发",
  "city": "杭州",
  "role_terms": ["Agent 应用开发 社招", "AI应用研发 工具调用"]
}
```

- `status` 写 `confirmed`、`confirmed_on` 写你确认范围的那天，`confirmation_reference` 写依据（比如你自己的备忘）。
- `role_terms` 只用于检索，不等于入选条件；真实岗位仍要逐项核对专业、年限、地点、在招状态。
- `selection_boundary` 写清边界，防止检索词无限扩张。

### 3.5 可选：放简历

```powershell
Copy-Item 你的简历.pdf config\resume.pdf
```

`config/resume.md` / `config/resume.pdf` / `config/photo.png` 都在 `.gitignore` 里。没有简历也能先跑 dry-run，只是做不了「投递准备」这一步。

## 4 首次 dry-run 走查

**默认全部 dry-run：不真实投递、不真实打招呼。** 下面每一步都只读或只落本地文件。

### 4.1 `status` —— 先看现状（不需要浏览器）

```powershell
python -X utf8 scripts/chain.py status
```

预期：一段 JSON，形如

```json
{
  "ledger": {"jobs_total": 0, "decisions": {}, "ready_materials": 0, "submitted_receipts": 0},
  "ready_shortlist": [],
  "environment": {"cdp": {"url": "http://127.0.0.1:9222", "online": true, "browser": "Chrome/…", "tabs": []}, "ledger": {...}}
}
```

看到 `jobs_total: 0` 是正常的 —— 还没发现岗位。首次运行会自动创建 `data/ledger.sqlite3`。`environment.cdp.online` 为 `false` 说明第 1.4 步的 Chrome 还没起好。

### 4.2 `run` —— 串起全链路（需要浏览器）

前提：`scripts\browser_launch.cmd` 已启动 Chrome，且**已登录的标签停在目标平台的搜索结果页**（框架复用当前标签，不新建标签，避免重新过平台安全验证）。

```powershell
python -X utf8 scripts/chain.py run
```

它依次执行：`discover`（读当前标签的岗位列表）→ `import`（dry-run，只打印 APP-### 记录，不入库）→ `screen`（生成空白证据卡）→ `ready`（出清单）→ `apply`（只列命令，不投）。

预期输出依次出现：

```
[discover] node ...\browser_cdp.js --platform boss jobs
[discover] 前置：宿主机已运行 browser_launch.cmd，且已登录标签停留在目标平台搜索结果页
[discover] 提取 12 条 → ...\data\chain\jobs.json
[import] python ...\boss_discover.py --jobs-json ...\jobs.json
[ { "id": "APP-001", "company": "...", "title": "...", "city": "...", ... }, ... ]
# 共 12 条（dry-run，未入库）
{"cards": 0, "out_dir": "...data\\chain\\证据卡", "next": "填证据卡→…"}
[ready] python ...\ready_list.py --scope ready
{"output": "...data\\投递清单.md", "count": 0, "scope": "ready", "external_send": false}
{"ready_total": 0, "outsourcing_apply": 0, "register_only": 0, "dry_run": true, "send": false}
```

注意 `cards: 0` 和 `count: 0`：`run` 全程 dry-run，`import` 不入库、`screen` 只对台账里已有的岗位出卡，所以这里必然是 0 —— 这正好证明 `run` **没有产生任何破坏性写入**。dry-run 的编号默认从 `APP-001` 起；真正入库时自动取台账最大号 +1。

三条常见异常及含义：

| 输出 | 含义 | 怎么办 |
|---|---|---|
| `[discover] 输出非 JSON（浏览器未就绪或结果页无岗位）` | 端口没通，或当前标签不是搜索结果页 | 检查 `http://127.0.0.1:9222/json/version`，把标签切到搜索结果页 |
| `[discover] 提取 0 条` | 页面开了但选择器没命中（改版 / 反爬 / 未登录） | 先确认页面能正常看到岗位列表，必要时更新 `config/platforms.json` |
| `count: 0` | `ready` 只显示「材料已备」的岗位，第一次必然为空 | 正常，用 `--scope shortlist` 或 `--scope all` 看候选 |

### 4.3 （可选）让台账真的有数据

上面 `run` 故意没入库。想让后面的 `ready` / `check` 有内容可看，再跑这两条 —— 它们只写本地台账和文件，仍然不向任何平台发请求：

```powershell
python -X utf8 scripts/chain.py import --apply
python -X utf8 scripts/chain.py screen
```

预期：`import --apply` 打印入库统计 JSON；`screen` 打印 `{"cards": 12, "out_dir": "...\\data\\chain\\证据卡", "next": "填证据卡→company_check/job_check validate→shortlist 后 prepare/track"}`，并在 `data/chain/证据卡/APP-###/` 下生成 `company_card.json` 与 `job_card.json` 两份空白模板。

**这一步之后你有了一条真实的本地数据链**，但外部世界毫不知情。

### 4.4 `ready` —— 看候选清单

```powershell
python -X utf8 scripts/chain.py ready --scope shortlist
```

预期：打印 `{"output": "...data\\投递清单.md", "count": N, "scope": "shortlist", "external_send": false}`，并生成 Markdown 清单。每岗含投递入口、简历版本哈希、筛选结论与依据、下一行动。

三个 scope 的区别：`ready` = 材料已备、待投递；`shortlist` = 初筛候选；`all` = 台账里全部。**第一次跑多半是 `count: 0`**（刚入库的岗位决策还是 `pending`），这时用 `--scope all` 就能看到它们 —— 这是正常状态，不是链路坏了。

`external_send: false` 是硬事实：这个命令**不发送任何内容**，最后一下永远是你的手。

### 4.5 `check` —— 校验证据卡

```powershell
python -X utf8 scripts/chain.py check
```

`screen` 生成的证据卡是空白模板（C1–C5 / J1–J5 待填）。填完再跑这条，预期：

```json
{"checked": 3, "shortlist_ready": 1, "results": [{"job_id": "APP-001", "company_decision": "shortlist", "job_decision": "shortlist", "valid": true, "errors": []}]}
```

没填卡时会看到 `{"checked": 12, "shortlist_ready": 0, "results": [...]}`，其中每项 `valid: false` 并列出缺失字段 —— 这不是故障，是提醒你去读岗位、写结论。**工具不会替你判断一家公司值不值得投。**

### 4.6 这样就完成了一次闭环

到这里你已经验证了：环境通、配置被正确读取、台账能建、清单能出、证据卡能被校验。**没有任何外部副作用。**

## 5 首次真实投递前的检查清单与边界

真实投递是唯一会产生外部后果的动作。逐条确认后再打开：

- [ ] **登录由我本人完成**：账号、短信/图形验证码、新协议勾选，都是我点的。
- [ ] **敏感字段没有被采集**：身份证号、护照、人脸/生物识别不在 `投递数据.json` 里，也没有被填进任何表单。
- [ ] **先小范围试**：从外包 / 派遣类岗位开始，这类岗位判错成本低。正编岗与「在考虑范围」岗**只登记、不投递**。
- [ ] **一次一小批**：单批 3 个岗位、15 分钟上限（`batch_max_jobs` / `batch_max_minutes`），别一次全投。
- [ ] **遵守平台规则与频率限制**：不批量骚扰 HR、不刷投递、不绕过平台安全检查、不自动登录、不做验证码识别。
- [ ] **开关注释清楚**：确要真实投递时才临时打开授权，投完关回去；`submit` 不带 `--execute` 永远只定位不点击。
- [ ] **留回执**：投递后登记平台回执定位 + 实际简历版本哈希。提交结果未知时**先对账，不重投**。
- [ ] **接受 offer / 离职 / 迁居 / 薪酬底线**：全部由你本人决定，程序不代做也不代答。

## 6 与 DSH 会话协作

### 6.1 开一个新会话

新开一个 DSH 会话，第一句话就把边界说清楚，例如：

> 这是 OfferLoop 仓库（工作目录就在仓库根）。请先读 `docs/RUNBOOK.md` 和 `docs/能力手册.md`，然后用 `scripts/chain.py` 的固定命令带我跑：先 `status` 给我现状，再按我确认的范围帮我出 `ready --scope shortlist` 清单。全程默认 dry-run，任何投递、打招呼、回复 HR 的动作都必须先问我。投递数据在 `config/投递数据.json`，不要修改配置真值文件。

### 6.2 分工建议

| 谁 | 干什么 |
|---|---|
| deepseek-flash | 按固定命令执行（`status` / `discover` / `import` / `screen` / `ready` / `check`），整理输出，不改平台细节 |
| deepseek-v4-pro | 做岗位取舍、背调结论、话术微调、跟进回复的草拟 |
| 你 | 登录、验证码、真实投递授权、接受 offer、所有对外沟通的最终确认 |

### 6.3 进阶玩法（简述）

- **定时巡检**：如果你用的 DSH 环境支持定时任务，让它只跑 `chain.py status` 这类**只读**命令，把「到期跟进」「提交结果待核」的岗位推给你；真实外发仍然手动授权。
- **会话交接**：把本次 `status` 输出和清单路径贴进新会话，比复述上下文可靠。
- **多人复用**：换一个人使用时，只需换自己的 3 个配置文件，代码与适配器不动。

## 7 常见问题

**浏览器连不上（`environment.cdp.online: false`）**
Chrome 没用带 `--remote-debugging-port=9222` 的方式启动，或端口被占用。重跑 `scripts\browser_launch.cmd`，再访问 `http://127.0.0.1:9222/json/version` 验证。

**登录态失效了**
在那个专用 profile 的窗口里重新登录一次即可。登录态跟着 profile 走，别用别的 Chrome 窗口。**不要**复制 Cookie、不要导出会话 —— 既不稳也不该做。

**岗位解析失败 / 提取 0 条**
多半是反爬、页面改版或 SPA 未渲染完。先确认人工能正常看到列表；BOSS 这类强反爬平台解析失败是常态，可以改用牛客这类服务端渲染页取正文（`scripts/nowcoder_parse.py`），或人工打开详情页登记。**读不到就标「需浏览器或人工」，不要编造字段。**

**回复跟进节奏怎么定**
一句话能说清就别说三句。对方明确拒绝、明确不合适、或已经是终止性回复，就**不要再回**。没有回复时按你自己的检查日期跟进，并在台账里注明这是你的检查时间，不是招聘方的承诺。

**`ready` 清单一直是 0 条**
`ready` 只列材料已备的岗位。先用 `--scope shortlist` 或 `all` 看候选，再对通过的岗位做投递准备。

**能不能只填一部分配置就跑**
可以。`status`、`ready`、`check` 都不依赖浏览器；`投递数据.json` 缺字段只影响填表环节，不影响链路验证。
