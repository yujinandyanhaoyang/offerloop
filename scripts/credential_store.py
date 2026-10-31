"""本地凭据加密存储（Windows DPAPI，仅当前 Windows 用户可解密）。

凭据存 <项目根>/credentials/<key>.bin（DPAPI 加密，无独立密钥文件，目录已 gitignore）。
secret 走 stdin 传入，不经过命令行（避免进程列表泄露）。get 只供程序内部调用，禁止回显/写日志。

用法：
  echo <secret> | python -X utf8 scripts/credential_store.py set <key>
  python -X utf8 scripts/credential_store.py get <key>   # 输出明文（程序内部用）
  python -X utf8 scripts/credential_store.py list        # 只列 key
  python -X utf8 scripts/credential_store.py del <key>
"""
import ctypes
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / 'credentials'


class DATA_BLOB(ctypes.Structure):
    _fields_ = [('cbData', ctypes.c_uint32), ('pbData', ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes):
    buf = ctypes.create_string_buffer(data, len(data))
    return DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))


def _protect(data: bytes) -> bytes:
    inp = _blob(data)
    out = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    if not crypt32.CryptProtectData(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError('CryptProtectData failed')
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def _unprotect(data: bytes) -> bytes:
    inp = _blob(data)
    out = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    if not crypt32.CryptUnprotectData(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError('CryptUnprotectData failed')
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def set_secret(key, secret):
    if not secret:
        raise ValueError('empty secret')
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / (key + '.bin')).write_bytes(_protect(secret.encode('utf-8')))


def get_secret(key):
    p = DIR / (key + '.bin')
    if not p.exists():
        raise KeyError(key)
    return _unprotect(p.read_bytes()).decode('utf-8')


def list_keys():
    if not DIR.exists():
        return []
    return sorted(p.stem for p in DIR.glob('*.bin'))


def del_secret(key):
    (DIR / (key + '.bin')).unlink(missing_ok=True)


def main():
    if len(sys.argv) < 2:
        print('用法: set <key>（secret 走 stdin） | get <key> | list | del <key>', file=sys.stderr)
        return 1
    cmd = sys.argv[1]
    try:
        if cmd == 'set' and len(sys.argv) >= 3:
            secret = sys.stdin.read().strip('\r\n')
            set_secret(sys.argv[2], secret)
            print(json.dumps({'set': sys.argv[2], 'stored': True}))
        elif cmd == 'get' and len(sys.argv) >= 3:
            print(get_secret(sys.argv[2]))
        elif cmd == 'list':
            print(json.dumps({'keys': list_keys()}))
        elif cmd == 'del' and len(sys.argv) >= 3:
            del_secret(sys.argv[2])
            print(json.dumps({'deleted': sys.argv[2]}))
        else:
            print('用法: set <key>（secret 走 stdin） | get <key> | list | del <key>', file=sys.stderr)
            return 1
    except (KeyError, OSError, ValueError) as e:
        print(json.dumps({'error': str(e)}), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
