# 面经研究与本地训练

方法见 [材料与训练](材料与训练.md)。题源归个人笔面线，默认不发布云端，初始化也不启动采集。

## 工具

- interview_drill.py 不依赖题源配置，直接进行本地原回答、纠偏与缺口记录，见 [训练说明](../skills/interview-drill/SKILL.md)。
- interviews.py 提供 plan、collect、validate、render、verify。它不替代搜索和语义审查，也不会自动发布。使用 --help 查看参数。
- 初次研究时将 config/interview-harness.example.json 复制到实例配置目录（默认 .local/config/）的 interview-harness.json，按目标岗位填写 search_terms；留空时 plan 明确提示尚未配置。旧行业线配置仅兼容读取，迁移后以实例配置为准，不保留两份。
- dataset/evidence 指向实例根下的私有材料。缺少历史数据或飞书绑定时仍能生成研究计划，不要求创建云端页面或 project-memory.json。

原帖需明确招聘身份、经历时间、问题和来源，区分原创、转载与推广。collect 的抓取成功不能替代语义核验。只用当前受支持网络工具，遇到登录或不可读时说明限制。

需要人阅读的当前题源可直接维护本地材料；render 是可选的既有云端稿件渲染器，只有明确需要相应 XML/Markdown 产物时使用，不为一次研究同时保存多个格式。飞书发布须单独授权并使用已接入工具，verify 对读回结果进行核对；失败和未知保留，先查已有写入。

一次性抓取和转换提炼后清理，继续训练要用的原题、用户回答、缺口和复验依据按实际用途留存。工具测试不证明新来源已核实，也不证明招聘效果。
