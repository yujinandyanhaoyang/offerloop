"""OfferLoop 路径配置。

优先级：环境变量 > 本地实例配置 offerloop.local.json > 通用默认。
- 本地实例：<repo>/workspace/offerloop.local.json；兼容原根目录配置。相对路径按配置所在目录解析。
- OFFERLOOP_HOME      数据目录（台账/证据/回执，不入库），默认 <repo>/workspace/data
- OFFERLOOP_CONFIG    个人执行配置目录，默认 <repo>/workspace/config
- OFFERLOOP_ADAPTERS  通用平台适配配置，默认 <repo>/scripts/config
"""
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent      # scripts/
REPO = HERE.parent                          # 项目根目录
BUNDLED_CONFIG = HERE / 'config'             # 公开适配与空配置，不能写个人资料

_LOCAL = None
_override = os.environ.get('OFFERLOOP_LOCAL')
_candidates = (Path(_override),) if _override else (
    REPO / 'workspace' / 'offerloop.local.json', REPO / 'offerloop.local.json', REPO.parent / 'offerloop.local.json')
for _cand in _candidates:
    if _cand.is_file():
        _LOCAL = _cand
        break
if _override and _LOCAL is None:
    raise FileNotFoundError(f'OFFERLOOP_LOCAL does not exist: {_override}')

_cfg = {}
_base = REPO / 'workspace'
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


HOME = _resolve('home', 'OFFERLOOP_HOME', _base / 'data')
CONFIG = _resolve('config', 'OFFERLOOP_CONFIG', _base / 'config')
ADAPTERS = _resolve('adapters', 'OFFERLOOP_ADAPTERS', BUNDLED_CONFIG)
if (not os.environ.get('OFFERLOOP_ADAPTERS') and ADAPTERS == (REPO / 'config').resolve()
        and not ADAPTERS.exists()):
    # Only the former built-in location has moved; never redirect a custom adapter directory.
    ADAPTERS = BUNDLED_CONFIG
PERSONAL = _resolve('personal', 'OFFERLOOP_PERSONAL', _base / 'profile')

# 项目实例根：offerloop.local.json 所在目录（默认 workspace）
PROJECT_ROOT = _base


def recorded_path(value):
    """Resolve saved artifact locations without rewriting historical event evidence."""
    normalized = str(value).replace('\\', '/')
    for old, new in sorted(_cfg.get('artifact_relocations', {}).items(), key=lambda p: -len(p[0])):
        old = old.replace('\\', '/').rstrip('/')
        if normalized == old or normalized.startswith(old + '/'):
            target = (PROJECT_ROOT / new / normalized[len(old):].lstrip('/')).resolve()
            if not target.is_relative_to(PROJECT_ROOT.resolve()):
                raise ValueError('artifact relocation must stay inside workspace')
            return target
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def artifact_reference(path):
    """New records use portable workspace-relative paths when possible."""
    path = Path(path).resolve()
    return path.relative_to(PROJECT_ROOT.resolve()).as_posix() if path.is_relative_to(PROJECT_ROOT.resolve()) else str(path)

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
PROFILE = PERSONAL / '投递数据.json'
RESUME = _resolve('resume', 'OFFERLOOP_RESUME', PERSONAL / 'resume.md')
INTERVIEW_LEDGER = _resolve('interview_ledger', 'OFFERLOOP_INTERVIEW_LEDGER', HOME / 'interview-ledger.json')
INTERVIEW_BATCHES = _resolve('interview_batches', 'OFFERLOOP_INTERVIEW_BATCHES', HOME / 'batches')
INTERVIEW_BATCH_PATTERN = _cfg.get('interview_batch_pattern', 'batch-{batch:02d}.md')
ATTACHMENTS = _resolve('attachments', 'OFFERLOOP_ATTACHMENTS', HOME)
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
