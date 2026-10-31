"""OfferLoop 路径配置。

优先级：环境变量 > 本地实例配置 offerloop.local.json > 通用默认。
- 本地实例：<repo>/offerloop.local.json 或 <repo>/../offerloop.local.json（相对路径按该文件所在目录解析）
- OFFERLOOP_HOME      数据目录（台账/证据/回执，不入库），默认 <repo>/data
- OFFERLOOP_CONFIG    项目配置目录（投递数据/执行策略/当前检索范围），默认 <repo>/config
- OFFERLOOP_ADAPTERS  平台适配配置目录（harness/field_mapping/platforms/companies），默认同 CONFIG
"""
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent      # scripts/
REPO = HERE.parent                          # harness 目录

_LOCAL = None
for _cand in (REPO / 'offerloop.local.json', REPO.parent / 'offerloop.local.json'):
    if _cand.is_file():
        _LOCAL = _cand
        break
if _LOCAL is None and os.environ.get('OFFERLOOP_LOCAL'):
    _p = Path(os.environ['OFFERLOOP_LOCAL'])
    if _p.is_file():
        _LOCAL = _p

_cfg = {}
_base = REPO
if _LOCAL is not None:
    _cfg = json.loads(_LOCAL.read_text(encoding='utf-8'))
    _base = _LOCAL.resolve().parent


def _resolve(key, env_name, default):
    env = os.environ.get(env_name)
    if env:
        return Path(env).resolve()
    value = _cfg.get(key)
    if value:
        p = Path(value)
        return (p if p.is_absolute() else _base / p).resolve()
    return default.resolve()


HOME = _resolve('home', 'OFFERLOOP_HOME', REPO / 'data')
CONFIG = _resolve('config', 'OFFERLOOP_CONFIG', REPO / 'config')
ADAPTERS = _resolve('adapters', 'OFFERLOOP_ADAPTERS', CONFIG)

# 数据（运行时/个人，不入库）
LEDGER = HOME / 'ledger.sqlite3'
CHAIN_DIR = HOME / 'chain'
RECEIPTS = HOME / 'receipts'
BROWSER_STATE = HOME / 'browser-circuit.json'
FEISHU_DIR = HOME / 'feishu'
PLATFORM_STATE = HOME / '平台接入状态.json'

# 项目配置
POLICY = CONFIG / '执行策略.json'
SCOPE = CONFIG / '当前检索范围.json'
PROFILE = CONFIG / '投递数据.json'
RESUME = CONFIG / 'resume.md'
READY_OUTPUT = HOME / '投递清单.md'

# 平台适配配置
HARNESS = ADAPTERS / 'harness.json'
FIELD_MAPPING = ADAPTERS / 'field_mapping.json'
PLATFORMS = ADAPTERS / 'platforms.json'
COMPANIES = ADAPTERS / 'companies.json'

# 外包岗判定标记（启发式；默认通用关键词，个人目标公司经环境变量或本地配置覆盖，不入库）
_DEFAULT_OUTSOURCING_MARKERS = ('外包', '派遣', '劳务', 'od', 'od外包')
_om = os.environ.get('OFFERLOOP_OUTSOURCING_MARKERS') or _cfg.get('outsourcing_markers')
if isinstance(_om, str):
    OUTSOURCING_MARKERS = tuple(m.strip() for m in _om.split(',') if m.strip())
elif _om:
    OUTSOURCING_MARKERS = tuple(_om)
else:
    OUTSOURCING_MARKERS = _DEFAULT_OUTSOURCING_MARKERS
