# 面经研究工具

面向 OfferLoop 的现有Harness增量。规范只维护在个人项目「规则\职业适配工作流.md」；本页维护工具契约。配置与当前数据入口见个人项目根目录 interview-harness.json，Skill 在个人项目 .agents/skills/career-interviews/。Python标准库，无新增服务、认证或依赖。

## 工具分工

| 工作 | 入口 | 能证明什么 |
|---|---|---|
| 检索、读原文 | 当前网页search/open | 真实读取到的文本；不保证发帖身份真实 |
| 牛客原页提取、缓存 | `interviews.py collect` | 原页元数据、作者、全文内容哈希；正文另交Agent审查 |
| 日期、来源去重、必要字段 | `interviews.py validate` | 输入字段及证据一致性；不代替语义判真 |
| 本地与飞书表格草稿 | `interviews.py render` | 从同一数据确定性生成Markdown/XML，拒绝覆盖 |
| 知识库写入 | 现有lark-doc/lark-wiki、`lark-cli` | 当次授权内的真实回执；不由本工具自动发布 |
| 写后读回 | `interviews.py verify` | 正文、链接顺序和表格数一致；不等于浏览器视觉验收 |

不新增MCP：现有网页工具、CLI和本地脚本已可完成各环节；有新增能力缺口时再评估，不为同一API另包服务。

## 运行

以下从Personal_log目录执行。`plan`默认先近一个月；不足时按问题扩至三至六个月。显式范围优先。

```powershell
python -X utf8 scripts/interviews.py plan --since 2025-09-01 --until 2026-10-26
python -X utf8 scripts/interviews.py validate
python -X utf8 scripts/interviews.py plan --topic sdet-social --since 2026-04-26 --until 2026-10-26
python -X utf8 scripts/interviews.py validate --topic sdet-social
```

`plan`返回查询词、已知原帖、当前飞书绑定及工具路由，不自动搜索或触发写入。每批先看已有证据，只补影响本次结论的资料。

主题配置隔离dataset、evidence、search_terms与binding_key。`plan/validate/render`的`--topic`默认agent，测开社招用sdet-social；`--input/--evidence`可覆盖本轮文件。`selection.track`可限定本批只收社招，`analysis`保存有来源编号的发现与建议，`mapping_title`适配不同岗位能力表。新增主题不需要另建采集器或MCP。

候选文件为JSON列表：`[{"source_id":"本批唯一ID","url":"真实原帖HTTPS链接"}]`。`collect --sources <候选.json> --cache <本批缓存.json> --show-body`读取明确的公开原页；默认复用成功缓存，显式`--refresh`才重取。新批最多30个候选，同源失败最多两次。超限/无正文保留状态，不能伪装读取成功；缓存中不保存IP、联系方式、凭据或完整网页，只留短摘录和哈希。

数据复用当前面经JSON：`entries[]`含id/company/role/track/author/location/priority、面试/发布/编辑时间、questions/coding/process/why/limitations以及`sources[]`。每个source含source_id/title/url/dates；对应缓存须保存作者、原文读取状态与完整日期。日期对象格式为 `{"createdAt":{"timestamp_ms":1790129116000,"iso":"2026-09-23T10:05:16+08:00"}}`；取实际原页字段，不能复制示例给新来源。

每条entry另有 `review`：`body_read:true`、`questions_checked:true`、`promotion_in_body:false`、`experience_claim:"candidate_self_report"`，由Agent逐篇审查后填写，不能由采集器自动设置。若广告/亲历不确定，放入exclusions，不填合格标记。`range.since/until`固定当批窗口；同作者同公司多轮合并。确为不同流程时，`separate_flow`写可核区分依据，不能仅改ID规避去重。

对于其他平台，Agent通过已授权工具读取后按同一字段登记；日期只有月日、正文不可读、仅有转载的来源不进入已核主表。页面失败状态不能直接手工改成成功；必须保存补读方式、时间及所核事实。

先按现有lark-doc创建工作流执行init-draft，取得真实draft_path，然后：

```powershell
python -X utf8 scripts/interviews.py render --input <本轮资料.json> --evidence <原页证据.json> --out-prefix <本轮新文件前缀> --draft <init-draft返回的XML路径>
lark-cli docs +script --command parse --content '@<同一个XML路径>' --format json
```

`render`先validate。已有文件不会覆盖；修改当前材料时由Agent局部合并并保留修订依据，不能重复生成第二份“现行版”。未处理的证据字段会直接阻止渲染。

## 发布与对账

发布前读本地绑定，不读取无关云端历史。相同主题和范围的增量用原页面局部更新；独立主题或明确要求新页时，复用lark-doc工作流及真实知识库父节点。认证或API报错交给对应lark技能；不安装额外工具、不偷偷换身份。

写入后将 `docs +fetch --doc <本次文档ID> --detail with-ids --as user` 的完整JSON保存本地，再运行：

```powershell
python -X utf8 scripts/interviews.py verify --expected <本次最终XML> --readback <本次读回.json> --output <验证回执.json>
```

验证只忽略空白及URL中等价的Unicode百分号编码，保留链接顺序和实际目标。局部更新时使用同一影响范围的预期XML和fetch片段。写入回执缺失、结果未知或验证失败时，保留未完成状态，先回查已创建的文档，不重建。

## 已验证范围

2026-10-26首次封装以当前已交付的14组/17篇原帖作为回放样本，校验、重渲染及旧云端回执对账由本地验证记录证明；它不构成新一轮市场调研。没有前后耗时基线，不报效率提升百分比。Skill的自动发现依赖后续会话加载工作区`.agents/skills`；当前会话可以按项目AGENTS中的精确路径读取，不声称已热加载到其他会话。

Skill路径和发现机制依据：[OpenAI官方技能文档](https://learn.chatgpt.com/docs/build-skills)。现有脚本回放不代表所有平台采集、将来的网页结构或后续模型均已验证。

2026-10-26跨岗位实跑：测开社招窗口2026-04-26—10-26，复核5篇原帖、5家公司、3位作者，复用同一采集/日期去重/语义审查/渲染/飞书读回链路；必要适配为岗位主题隔离、单一招聘身份约束和分析字段。12项测试通过，新云端2张表、16个链接读回一致，详见项目`.local/测开面经-20261026/verification.json`。这些线索来自已有参考库的重新核验，并非5篇新发现；新增检索未取得合格独立样本。结论限于两个岗位主题与牛客公开页，不证明全职业、全平台通用，也没有效率收益基线。
