"""Create missing local workspace files; never replace existing user data."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def relative(path, base):
    try:
        return os.path.relpath(path, base).replace('\\', '/')
    except ValueError:  # Windows workspaces on a different drive
        return str(path.resolve()).replace('\\', '/')


def write_missing(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('x', encoding='utf-8') as stream:
            stream.write(content)
        return True
    except FileExistsError:
        return False


def initialize(workspace=None):
    override = os.environ.get('OFFERLOOP_LOCAL')
    if workspace is not None:
        if any(os.environ.get(key) for key in ('OFFERLOOP_HOME', 'OFFERLOOP_CONFIG', 'OFFERLOOP_PERSONAL', 'OFFERLOOP_ADAPTERS', 'OFFERLOOP_RESUME', 'OFFERLOOP_ATTACHMENTS')):
            raise ValueError('创建另一使用者的实例前，请清除 OFFERLOOP 路径覆盖环境变量。')
        manifest = Path(workspace).resolve() / 'offerloop.local.json'
    elif override:
        manifest = Path(override).resolve()
        if not manifest.is_file():
            raise FileNotFoundError('OFFERLOOP_LOCAL 配置不存在，请修正或指定 --workspace')
    else:
        manifest = next((p for p in (REPO / 'offerloop.local.json', REPO.parent / 'offerloop.local.json')
                         if p.is_file()), REPO / 'offerloop.local.json')
    root = manifest.parent
    settings = {'home': 'data', 'config': '.local/config', 'personal': '.local/profile',
                'adapters': relative(REPO / 'config', root),
                'resume': '内容线/简历.md', 'attachments': '.local/profile'}
    created = []
    if write_missing(manifest, json.dumps(settings, ensure_ascii=False, indent=2) + '\n'):
        created.append('offerloop.local.json')
    settings = json.loads(manifest.read_text(encoding='utf-8-sig'))

    def location(key, env, default):
        if os.environ.get(env):
            return Path(os.environ[env]).resolve()
        value = settings.get(key, default)
        path = Path(value)
        return path.resolve() if path.is_absolute() else (root / path).resolve()

    config = location('config', 'OFFERLOOP_CONFIG', '.local/config')
    personal = location('personal', 'OFFERLOOP_PERSONAL', settings.get('config', '.local/config'))
    home = location('home', 'OFFERLOOP_HOME', 'data')
    for name, folder in [('执行策略', config), ('当前检索范围', config), ('投递数据', personal)]:
        target = folder / (name + '.json')
        if write_missing(target, (REPO / 'config' / (name + '.example.json')).read_text(encoding='utf-8')):
            created.append(str(target))
    for template in sorted((REPO / 'templates' / 'workspace').rglob('*')):
        if not template.is_file():
            continue
        target = root / template.relative_to(REPO / 'templates' / 'workspace')
        values = {'METHODS': REPO / 'docs', 'HARNESS': REPO, 'PROFILE': personal / '投递数据.json',
                  'SCOPE': config / '当前检索范围.json', 'POLICY': config / '执行策略.json', 'DATA': home}
        content = template.read_text(encoding='utf-8')
        for key, value in values.items():
            content = content.replace('{{' + key + '}}', relative(value, target.parent))
        if write_missing(target, content):
            created.append(str(target))
    if root != REPO:
        entry = '# OfferLoop 私有工作区\n\n先读 [通用协作入口](' + relative(REPO / 'AGENTS.md', root) + ')。\n'
        write_missing(root / 'AGENTS.md', entry)
    return {'workspace': str(root), 'manifest': str(manifest), 'created': created,
            'next': '阅读 docs/建档与接续.md，通过对话补充档案；已有实例只补缺失文件。'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, help='另一使用者的空目录；后续设置 OFFERLOOP_LOCAL')
    args = parser.parse_args()
    result = initialize(args.workspace)
    view = Path(result['workspace']) / 'memory/CURRENT_STATE.md'
    if '<!-- offerloop:current-work -->' in view.read_text(encoding='utf-8-sig'):
        done = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(REPO / 'scripts/workspace.py'), 'refresh'],
            env=dict(os.environ, OFFERLOOP_LOCAL=result['manifest']), capture_output=True, text=True, encoding='utf-8')
        if done.returncode:
            raise RuntimeError(done.stderr)
        result['current_work'] = str(view)
    else:
        result['migration'] = '现有接续需先迁入统一工作状态，见 docs/工作闭环.md；未覆盖旧记忆。'
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
