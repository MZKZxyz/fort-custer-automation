"""Exact-tree server QA preparation. Executing repository tests requires isolation.

This command never runs npm or repository code on the controller. Asset staging
commands below belong inside a disposable networked preparation VM; test runs
use a separate, networkless QA guest/image.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from trust import digest

SOURCE = 'c4f480abb309a7a4d141b20ab462552a868ef0e3'
TREE = '9015875cca2b85a845f7168ba237c5935e86445c'
REQUIRED = ('package-lock.json', 'test/analyzer.test.js', 'test/report-validation.test.js',
            'test/completions.test.js', 'tools/maze-analyzer/cli.js')
ASSETS = ('mongodb/mongod', 'native/bcrypt_lib.node', 'npm-cache')


def source_evidence(root):
    root = Path(root)
    # Index hashes alone are insufficient: ensure the working files match too.
    from independent_qa import git
    actual = git(root, 'write-tree').decode().strip()
    commit = git(root, 'rev-parse', '--verify', 'HEAD^{commit}').decode().strip()
    if actual != TREE or commit != SOURCE:
        raise ValueError('Reviewed server tree mismatch')
    working_diff = git(root, 'diff', '--no-ext-diff', '--no-textconv', '--exit-code')
    if git(root, 'ls-files', '--others', '--exclude-standard').strip():
        raise ValueError('Untracked files in reviewed QA source')
    for name in REQUIRED:
        if not (root/name).is_file() or (root/name).is_symlink():
            raise ValueError('Required server QA source absent')
    return dict(source=SOURCE, tree=TREE, lock_sha256=hashlib.sha256((root/'package-lock.json').read_bytes()).hexdigest(),
                baseline_diff_sha256=hashlib.sha256(working_diff).hexdigest(), protected_changes=[],
                diff_scope='verified baseline only; no live candidate created')


def verify_assets(root, expected):
    """A reviewed expected manifest is pinned externally, never generated as proof.

    Include every npm cache object, the native bcrypt binding, the MongoDB binary
    and their shared library dependencies for the pinned QA image ABI.
    """
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('QA asset root must be a real directory')
    manifest = expected['files']
    found = {}
    for path in root.rglob('*'):
        if path.is_symlink(): raise ValueError('QA asset links rejected')
        if path.is_file(): found[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not manifest or found != manifest or expected['source'] != SOURCE or expected['tree'] != TREE:
        raise ValueError('QA assets incomplete, stale or modified')
    if not all((root/name).exists() for name in ASSETS):
        raise ValueError('Missing offline npm cache, native binding or test MongoDB')
    if not any(name.startswith('npm-cache/') for name in found):
        raise ValueError('Empty npm cache')
    return dict(manifest=digest(expected), assets=len(found), source=SOURCE, tree=TREE)


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest='action', required=True)
    inspect = commands.add_parser('inspect'); inspect.add_argument('source', type=Path)
    assets = commands.add_parser('verify-assets'); assets.add_argument('assets', type=Path); assets.add_argument('reviewed_manifest', type=Path)
    run = commands.add_parser('run'); run.add_argument('source', type=Path); run.add_argument('--image', required=True)
    run.add_argument('--assets', type=Path, required=True); run.add_argument('--reviewed-manifest', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'inspect':
        result = source_evidence(args.source)
        result.update(suite='not_run', reason='Inspection does not execute the isolated real server suite')
    elif args.action == 'verify-assets':
        result = verify_assets(args.assets, json.loads(args.reviewed_manifest.read_text()))
    else:
        evidence = source_evidence(args.source)
        assets = verify_assets(args.assets, json.loads(args.reviewed_manifest.read_text()))
        # Image content/ABI + manifest matching must additionally be checked by
        # independent deployment collector. This is rehearsal QA, never VM attestation.
        from infrastructure import ContainerQA
        import tempfile
        from independent_qa import export
        with tempfile.TemporaryDirectory() as d:
            export(args.source, SOURCE, d)
            result = ContainerQA(args.image, 'MZKZxyz/fort-custer-server', synthetic=False).run_exact(
                Path(d), ('policy', 'MZKZxyz/fort-custer-server'), SOURCE, SOURCE)
        result.update(evidence=evidence, assets=assets, vm_attestation=False)
    print(json.dumps(result, indent=2))
    return 1 if result.get('status') == 'failed' else 0


if __name__ == '__main__': raise SystemExit(main())
