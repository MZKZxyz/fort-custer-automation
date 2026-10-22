"""Real dependency-free server checks in disposable gVisor containers.

Subset only: passing cannot satisfy the mandatory full server_qa readiness gate.
No host mounts, dependency scripts, production connections or live agent calls.
"""
import json
from pathlib import Path
import tempfile
from independent_qa import export
from infrastructure import docker
from server_qa import SOURCE, TREE, source_evidence


def run(source):
    source = Path(source)
    provenance = source_evidence(source)
    root = Path(__file__).resolve().parents[1]
    base = json.loads((root/'infra/images.lock.json').read_text())['node']
    results = []
    with tempfile.TemporaryDirectory(prefix='fc55-subset-') as d:
        context = Path(d)
        export(source, SOURCE, context/'source')
        # Use the same trusted Python runner/protocol as the isolated QA image;
        # the source is delivered via stdin into fresh tmpfs, never host mounts.
        python_base = json.loads((root/'infra/images.lock.json').read_text())['python']
        (context/'Dockerfile').write_text('ARG NODE\nARG PYTHON\nFROM ${NODE} AS node\nFROM ${PYTHON}\nCOPY --from=node /usr/local/bin/node /usr/local/bin/node\nCOPY --chmod=0444 worker_entry.py probe.py /opt/\nWORKDIR /workspace\nUSER 65531:65531\nENTRYPOINT ["python3","-I","/opt/worker_entry.py"]\n')
        import shutil
        shutil.copyfile(root/'infra/worker_entry.py', context/'worker_entry.py')
        shutil.copyfile(root/'infra/probe.py', context/'probe.py')
        docker('build', '--network=none', '--build-arg', 'NODE='+base, '--build-arg', 'PYTHON='+python_base,
               '--tag', 'fc55-server-subset:rehearsal', str(context), timeout=600)
        image = json.loads(docker('image', 'inspect', 'fc55-server-subset:rehearsal').stdout)[0]['Id']
        from infrastructure import ContainerRuntime, source_files, source_modes, artifact_digest
        files, modes = source_files(context/'source'), source_modes(context/'source')
        result = ContainerRuntime().run('qa', image, dict(files=files, modes=modes, artifact=artifact_digest(files,modes),
                    source=SOURCE, candidate=SOURCE, policy='server-analyzer-subset'))
        if (result.get('source') != SOURCE or result.get('candidate') != SOURCE
                or result.get('policy') != 'server-analyzer-subset'
                or result.get('artifact') != artifact_digest(files,modes)):
            raise ValueError('Subset provenance mismatch')
        results = result['tests']
        if ([t['name'] for t in results] != ['analyzer', 'reports', 'smoke', 'syntax']
                or any(t['status'] != 'passed' or t['exit_code'] != 0 for t in results)):
            raise ValueError('Required subset checks failed or are missing')
    return dict(kind='real-server-subset', source=SOURCE, tree=TREE, provenance=provenance, image=image,
                checks=results, full_suite_passed=False, vm_attestation=False,
                missing=['full unit discovery', 'completion integration', 'offline npm cache', 'bcrypt native binding', 'test-only MongoDB'])


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('source',type=Path)
    print(json.dumps(run(parser.parse_args().source),indent=2))
