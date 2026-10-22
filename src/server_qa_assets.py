"""Offline dependency inventory, not asset acquisition or QA attestation."""
import argparse
import base64
import binascii
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
from server_qa import SOURCE, TREE


def plan(lock_bytes):
    lock = json.loads(lock_bytes)
    if lock.get('lockfileVersion') != 3 or not isinstance(lock.get('packages'), dict):
        raise ValueError('Reviewed npm v3 lock required')
    packages = []
    for name, package in sorted(lock['packages'].items()):
        if not name:
            continue
        url, integrity = package.get('resolved'), package.get('integrity')
        if (not isinstance(url, str) or urlsplit(url).scheme != 'https'
                or urlsplit(url).hostname != 'registry.npmjs.org'
                or not isinstance(integrity, str) or not integrity.startswith('sha512-')
                or not isinstance(package.get('version'), str)):
            raise ValueError('Unpinned or unsupported dependency; independent review needed')
        try:
            if len(base64.b64decode(integrity[7:], validate=True)) != 64:
                raise ValueError('Invalid SHA-512 digest length')
        except (ValueError, binascii.Error) as exc:
            raise ValueError('Invalid lockfile integrity digest') from exc
        if urlsplit(url).username or urlsplit(url).password or urlsplit(url).fragment:
            raise ValueError('Dependency URL contains credentials or fragment')
        packages.append(dict(path=name, version=package['version'], url=url, integrity=integrity,
                             install_script=package.get('hasInstallScript', False)))
    bcrypt = lock['packages'].get('node_modules/bcrypt', {})
    if bcrypt.get('version') != '5.1.1':
        raise ValueError('Reviewed native binding version changed')
    return dict(schema=1, status='blocked', source=SOURCE, tree=TREE,
                lock_sha256=hashlib.sha256(lock_bytes).hexdigest(), packages=packages,
                native=dict(package='bcrypt', version='5.1.1', output='native/bcrypt_lib.node',
                            platform='linux-x64', required_probe='hashSync and compareSync in pinned Node image'),
                mongodb=dict(version='8.0.16', output='mongodb/mongod',
                             archive_sha256=None, independent_vendor_checksum_required=True,
                             scope='temporary loopback database only'),
                qa_image=json.loads((Path(__file__).resolve().parents[1]/'infra/images.lock.json').read_text()),
                missing=['complete offline npm cache', 'independently verified MongoDB archive',
                         'reviewed native binding and transitive ELF shared libraries',
                         'independently approved complete asset manifest', 'disposable preparation VM',
                         'fresh network-isolated QA VM and watchdog'],
                suite=['npm ci --offline --ignore-scripts --no-audit --no-fund',
                       'native binding load/hash probe', 'node --test',
                       'node --test test/analyzer.test.js', 'node --test test/completions.test.js',
                       'deterministic analyzer smoke', 'syntax and protected-file diff checks'],
                production_database=False, ready=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('lock', type=Path)
    args = parser.parse_args()
    print(json.dumps(plan(args.lock.read_bytes()), indent=2))
