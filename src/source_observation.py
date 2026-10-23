"""Fixed local Git reads and manifest hashing. No worker, approval or write actions."""
import hashlib
import json
import re
import subprocess
MODE = 'local_codex_development'
ALLOWED = ['test/analyzer.test.js', 'tools/maze-analyzer/solver.js']

def canonical(x):
    return json.dumps(x, sort_keys=True, separators=(',', ':'), ensure_ascii=True)

def digest(x):
    return hashlib.sha256(canonical(x).encode()).hexdigest()

def environment(home='/nonexistent'):
    # Deliberate allowlist, not a denylist of known API key spellings.
    return dict(PATH='/usr/bin:/bin', HOME=str(home), LANG='C.UTF-8',
                GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null',
                GIT_NO_REPLACE_OBJECTS='1', GIT_TERMINAL_PROMPT='0')

def git(root, *args):
    return subprocess.check_output(['/usr/bin/git', '-c', 'core.hooksPath=/dev/null',
        '-c', 'core.fsmonitor=false', '-C', str(root), *args], env=environment(),
        stderr=subprocess.PIPE, timeout=30)

def source_files(source, sha, allowed=None):
    if not re.fullmatch('[0-9a-f]{40}', sha):
        raise ValueError('Exact SHA required')
    if git(source, 'rev-parse', sha+'^{commit}').decode().strip() != sha:
        raise ValueError('Source identity mismatch')
    files = {}
    for entry in git(source, 'ls-tree', '-rz', sha).split(b'\0'):
        if not entry:
            continue
        meta, raw = entry.split(b'\t'); mode, kind, obj = meta.decode().split()
        name = raw.decode('utf-8')
        parts = name.split('/')
        if (mode not in ('100644', '100755') or kind != 'blob' or
            any(p in ('', '.', '..', '.git', '.codex', '.gitattributes', '.gitmodules') for p in parts) or
            name.startswith('/') or '\\' in name or any(ord(c)<32 for c in name) or
            any(p == '.env' or p.startswith('.env.') and p not in ('.env.example', '.env.sample') for p in parts)):
            raise ValueError('Unsafe repository entry')
        files[name] = (int(mode, 8) & 0o777, git(source, 'cat-file', 'blob', obj))
    if not set(ALLOWED if allowed is None else allowed) <= set(files):
        raise ValueError('Expected allowed files missing')
    return files

def manifest(files):
    return digest({k: [v[0], hashlib.sha256(v[1]).hexdigest()] for k,v in files.items()})
