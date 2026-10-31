# OfferLoop

求职执行 Harness：把「发现岗位 → 筛选 → 背调 → 投递 → 跟进 → 面试」做成可配置、可 dry-run 的求职流水线，供有同类求职需求的人针对自己的情况复用。

## 特性

- **三通用能力 + 平台适配器**：`greet`（打招呼）/ `apply`（投递）/ `update_resume`（更新简历），平台细节封装在 `config/`。
- **生命周期**：`chain.py` 提供 `discover → import → screen → check → shortlist → prepare → track → submit → followup`，默认全 dry-run。
- **数据一次定义、多平台复用**：个人信息只在 `config/投递数据.json` 定义一次。
- **分阶段背调**：初筛只做 C1–C5 + J1–J5（轻量）；跨过简历沟通关、进入笔试/面试邀约后才做全量三层×七维（含 C6 风险、C7 岗位真实性）。
- **安全默认**：dry-run 优先；真实投递仅外包岗且需授权；正编只登记不投。
- **一套话术 + 一套简历**：大规模招聘岗不逐岗打磨。

## 目录

```
offerloop/
├── README.md
├── LICENSE
├── .gitignore
├── scripts/        # 代码（chain.py / harness.py / pipeline.py / browser_cdp.js ...）
├── config/         # 配置（*.example.json 模板；真实配置 gitignored）
├── docs/           # 能力手册、海投链路、RUNBOOK、企业背调方法论、岗位筛选规则、通用话术
├── tests/          # 测试
└── data/           # 运行时数据（台账/证据，gitignored）
```

## 快速开始

1. 复制模板为真实配置：`config/投递数据.example.json → config/投递数据.json` 等（见下）。
2. 填真实信息：`投递数据.json`（姓名/手机/邮箱/简历）、`当前检索范围.json`（城市/岗位族）、`执行策略.json`（策略）。
3. 可选：把简历放 `config/resume.md` / `config/resume.pdf`。
4. 跑：
   ```bash
   python -X utf8 scripts/chain.py check      # 校验证据卡
   python -X utf8 scripts/chain.py submit     # dry-run 定位投递按钮（不点击）
   ```

### 配置模板
| 模板 | 复制为 | 作用 |
|---|---|---|
| `config/投递数据.example.json` | `config/投递数据.json` | 个人投递数据（定义一次） |
| `config/执行策略.example.json` | `config/执行策略.json` | 筛选/背调/执行策略 |
| `config/当前检索范围.example.json` | `config/当前检索范围.json` | 岗位族/城市检索范围 |

适配器配置（`harness.json` / `platforms.json` / `companies.json` / `field_mapping.json`）是通用的，可直接用，也可按平台维护。

## 环境变量

- `OFFERLOOP_HOME`：数据目录（台账/证据/回执），默认 `<repo>/data`。
- `OFFERLOOP_CONFIG`：项目配置目录，默认 `<repo>/config`。
- `OFFERLOOP_ADAPTERS`：平台适配配置目录，默认同 `OFFERLOOP_CONFIG`。

## 边界

- 登录、验证码、新协议、接受 offer、离职、迁居：由本人处理，程序不代做。
- 敏感字段（身份证号/护照/人脸/生物识别）：不采集不填写。
- 真实投递仅外包岗（如外企德科/华为OD），正编与「在考虑范围」岗只登记不投。
- 默认 dry-run，不自动外发。

## 许可

MIT，见 [LICENSE](LICENSE)。
