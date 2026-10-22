"""Build-time complete checksum validation of operator-staged offline assets."""
import hashlib
import json
from pathlib import Path
import shutil


def verify(root):
    root = Path(root)
    manifest = json.loads((root/'manifest.json').read_text())
    if not isinstance(manifest, dict) or not manifest:
        raise ValueError('Nonempty complete manifest required')
    files = {}
    for p in root.rglob('*'):
        if p.is_symlink():
            raise ValueError('Links prohibited in QA assets')
        if p.is_file() and p != root/'manifest.json' and p != root/'README.md':
            files[str(p.relative_to(root))] = p
    if set(files) != set(manifest):
        raise ValueError('Asset manifest incomplete')
    if not all(hashlib.sha256(p.read_bytes()).hexdigest() == manifest[name] for name,p in files.items()):
        raise ValueError('Asset checksum mismatch')
    if not (root/'mongodb/mongod').is_file() or not (root/'npm-cache').is_dir() or not (root/'browsers').is_dir():
        raise ValueError('Required QA assets absent')
    return files


if __name__ == '__main__':
    root=Path('/opt/assets')
    verify(root)
    for name in ('npm-cache','mongodb','browsers','native'):
        if name == 'native' and not (root/name).exists():
            continue # Older fixture images remain usable; real server QA refuses missing binding.
        shutil.copytree(root/name,Path('/opt')/name)
    Path('/opt/mongodb/mongod').chmod(0o555)
    shutil.rmtree(root)
