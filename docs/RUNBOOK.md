# 求职执行手册

首次使用先按 [建档与接续](建档与接续.md) 完成必要对话。以下命令从仓库根运行，路径由 offerloop.local.json 解析。代码管理状态，研究判断由助手依据真实来源完成。

## 发现、核验与准备

1. 未定方向先用 [筛选规则](行业线/岗位筛选规则.md) 探索。用户已接受的范围写入实例 config/当前检索范围.json，draft 不进入执行队列。
2. `python -X utf8 scripts/pipeline.py plan` 读取当前状态和下一动作，命令本身不联网。`start` 认领一个研究批次，只有准备执行时才调用；异常后先对账再继续。
3. 使用当前助手支持的公开检索工具核原 JD，区分在招状态、身份硬条件与个人证据。岗位数据以 `assistant.py import <私有岗位JSON>` 入库；字段结构参考 scripts/assistant.py 和 tests/test_assistant.py 中的纯测试样本，不能把样本作为真实岗位。
4. 公司与岗位证据使用 `chain.py screen` 生成待核卡，填写真实证据后用 check 校验，shortlist 写回结论。不同判定的未知与否决原因不得抹平。
5. 按 [材料方法](材料与训练.md) 准备简历，`chain.py prepare <APP-ID> --resume <现用简历>` 登记材料，`chain.py ready` 生成清单。完整参数见各命令 --help。

手动研究和用户自行投递同样适用，不要求启用浏览器自动化。执行策略中的批次上限只约束工具工作量，不是用户日程或投递承诺。

## 回执与反馈

`pipeline.py track <APP-ID> <私有JSON>` 更新跟进上下文，`pipeline.py record <APP-ID> <私有JSON>` 登记真实事件。事件需 stage、summary、evidence，提交须真实 receipt 和已准备材料对应的 resume_hash；原格式以脚本校验为准。可用 --help 查看入口。

只准备好材料不能写 submitted。结果未知先核原平台，不重复提交。招聘方回复、邀约、笔面、offer 和结束分别记实际状态。资格拒绝、无回复、技术缺口按 [反馈方法](材料与训练.md) 处理，下一动作需具体可执行。

`chain.py status` 查看本地状态，`assistant.py report` 生成本地清单，`workspace.py refresh` 刷新当前工作页（overview.py 为同一入口别名）。data 中的 SQLite 保留去重、操作回执和未完动作，不能为了清洁删除。

## 可选外部操作

默认 external_actions_enabled=false。任何投递、打招呼、更新在线简历或云端写入，均须相应授权与当前账户核对。既有授权持续有效，但建档授权不等于外发授权。

`execution.py routes` 查看适配入口，`execution.py prepare --platform <平台>` 生成字段计划。准备成功不代表登录、上传、保存或投递完成。带 --output 的私有计划含个人值，仅本地保存。profile.py 是旧专用表单解析器，格式受限，不用于通用建档。

页面工具见 [浏览器接入](DSH-上手.md)。选择器需现场核实，遵循当前宿主工具边界，遇到验证码或身份校验由本人处理。旧 chain submit 实际执行还保留外包岗位限制；这只是工具现有覆盖范围，不代表推荐外包或拒绝其他岗位。未适配岗位由本人投递并登记回执。

飞书进度通过 feishu_base.py 的预览和授权后的 --apply 同步。云端承载看板、跟进和复盘，训练原文留本地。写入结果未知先回查，成功后读回。真实平台行为和当前招聘状态须单独验证，离线测试不证明其有效。
