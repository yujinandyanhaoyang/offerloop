# 贡献指南

## 提交前
- 不提交个人数据：姓名、手机、邮箱、简历、真实台账、`.local/` 下的私有证据。
- 配置改动只改 `*.example.json` 模板，不改真实 `config/*.json`（已在 `.gitignore`）。
- 跑测试：`python -X utf8 -m unittest discover -s tests -p "test_*.py"`。

## 新增平台
1. 在 `config/platforms.json` 加平台选择器/搜索 URL/提交按钮。
2. 在 `config/harness.json` 的 `greet/apply/update_resume` 加平台适配。
3. 在 `config/field_mapping.json` 加表单字段映射（如需要）。
4. 用 dry-run 验证：`chain.py submit` 只定位不点击。

## 边界
- 不新增自动登录、验证码识别、绕过平台安全检查。
- 默认 dry-run；真实外发需使用者显式授权且仅外包岗。
