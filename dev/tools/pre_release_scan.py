# -*- coding: utf-8 -*-
"""Pre-release privacy scan for the GitHub upload folder.

Usage:
    python dev/tools/pre_release_scan.py            # scan project root
    python dev/tools/pre_release_scan.py <folder>   # scan any folder

Text files: simple substring check for local paths / usernames.
Binary files: look for drive-letter patterns, but only flag them when the
surrounding bytes are plaintext (printable) - random matches inside the
compressed PyInstaller payload are noise, not paths. URLs (http://) are
excluded for the same reason.

No hardcoded machine paths in this file itself.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if len(sys.argv) > 1:
    ROOT = sys.argv[1]
_SELF = os.path.abspath(__file__)  # detection patterns live here; skip self
SKIP_DIRS = {'.git', '__pycache__', 'build', 'dist', 'Github'}
TEXT_EXT = {'.py', '.md', '.ini', '.txt', '.c', '.gitignore', '.yml', '.yaml', '.json'}
BAD_TEXT = [b'G:\\', b'G:/', b'Emulators', b'Administrator', b'C:\\Users',
            b'Users\\', '模拟器插件'.encode('utf-8'),
            'Monster Hunter XX'.encode('utf-8')]

all_files = []
for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
    for fn in filenames:
        full = os.path.join(dirpath, fn)
        if fn == 'pre_release_scan.py':  # detector copies share the pattern list
            continue
        if fn in ('overlay_error.log',) or fn.endswith(('.pyc', '.log')):
            continue
        all_files.append((os.path.relpath(full, ROOT), full))

print('=== 待上传文件清单(%d 个)===' % len(all_files))
for rel, _ in sorted(all_files):
    print('  ' + rel)

print()
print('=== 隐私扫描 ===')
issues = 0
for rel, full in sorted(all_files):
    data = open(full, 'rb').read()
    hits = []
    ext = os.path.splitext(rel)[1].lower()
    if ext in TEXT_EXT or ext == '':
        for b in BAD_TEXT:
            if b in data:
                hits.append(b.decode('utf-8', 'replace'))
    else:  # binary: only plaintext-context drive paths count
        for pat in (rb'[A-Za-z]:\\', rb'[A-Za-z]:/'):
            for m in re.finditer(pat, data):
                ctx = data[max(0, m.start() - 24):m.start() + 32]
                printable = sum(1 for c in ctx if 32 <= c < 127 or c in (10, 13, 9))
                if printable / len(ctx) > 0.85 and b'://' not in ctx:
                    hits.append(repr(ctx))
        for b in (b'Emulators', b'Administrator', b'C:\\Users', b'Users\\'):
            if b in data:
                hits.append(b.decode('utf-8', 'replace'))
    if hits:
        issues += 1
        print('  [发现] %s -> %s' % (rel, hits))
print('发现问题: %d' % issues)
