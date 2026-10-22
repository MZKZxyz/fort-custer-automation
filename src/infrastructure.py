"""Offline infrastructure. This module cannot dispatch a real Codex task.

Docker enforces resource settings; gVisor is an additional sandbox, not a VM.
All workers use disposable size-bounded tmpfs, no host source/credential mounts.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from codex_adapter import Supervisor
from trust import canonical, require_live, sha

ROOT = Path(__file__).resolve().parent.parent
DOCKER = (shutil.which('docker') or '/usr/bin/docker', '--host=unix:///var/run/docker.sock')
IMAGE = re.compile(r'(?:[a-z0-9./_:-]+@)?sha256:[a-f0-9]{64}')


def tree_digest(files):
    return hashlib.sha256(canonical(files).encode()).hexdigest()


def source_files(root):
    files = {}
    for p in sorted(Path(root).rglob('*')):
        if p.is_symlink():
            raise ValueError('Links prohibited')
        if p.is_file():
            name = str(p.relative_to(root))
            if any(part in ('.git', 'node_modules', '__pycache__') or part.startswith('.env') for part in p.relative_to(root).parts):
                raise ValueError('Unexpected private or generated source')
            files[name] = p.read_bytes().decode('utf-8')
            if '\x00' in files[name]: raise ValueError('Binary source requires reviewed transport')
    if len(canonical(files).encode()) > 4*1024*1024:
        raise ValueError('Artifact size limit; binary/large transport requires separate review')
    return files


def source_modes(root):
    return {str(p.relative_to(root)): (0o755 if p.stat().st_mode & 0o111 else 0o644)
            for p in sorted(Path(root).rglob('*')) if p.is_file()}

def artifact_digest(files, modes):
    return tree_digest(dict(files=files,modes=modes))

def docker(*args, timeout=60):
    # No implicit remote daemon or user Docker context. Never print environment.
    return subprocess.run([*DOCKER, *args], check=True, capture_output=True, timeout=timeout)


def specification(role, image, name, *, runtime='runsc'):
    if role not in ('coding', 'qa', 'controller') or not IMAGE.fullmatch(image) or not re.fullmatch(r'fc54-[a-f0-9]{32}', name):
        raise ValueError('Role, immutable image and task identity required')
    if runtime != 'runsc':
        raise ValueError('Reviewed gVisor runtime required')
    uid = {'coding':65532,'qa':65531,'controller':65530}[role]
    # Identical approved settings are checked against Docker's effective config
    # before starting ANY process. No configurable volumes/env/commands here.
    return [*DOCKER, 'create', '--name', name, '--label', 'fc.sprint=5.4',
        '--runtime=runsc', '--network=none', '--cgroupns=private', '--pull=never', '--read-only', f'--user={uid}:{uid}',
        '--cap-drop=ALL', '--security-opt=no-new-privileges', '--pids-limit=128',
        '--memory=2g', '--memory-swap=2g', '--cpus=1', '--ipc=none',
        '--ulimit', 'fsize=8388608:8388608', '--ulimit', 'nofile=256:256',
        '--log-driver=none', '--stop-timeout=1', '--interactive',
        '--tmpfs', f'/workspace:rw,nosuid,nodev,size=256m,uid={uid},gid={uid},mode=0700',
        '--tmpfs', f'/tmp:rw,noexec,nosuid,nodev,size=64m,uid={uid},gid={uid},mode=0700',
        *[arg for key in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY','http_proxy','https_proxy','all_proxy','no_proxy') for arg in ('--env',key+'=')],
        '--env', f'FC_ROLE={role}', '--env', 'HOME=/tmp', '--workdir=/workspace', image]


def validate_inspection(data, role, image, name):
    """Fail closed on effective Docker config drift, including injected proxies."""
    specification(role, image, name) # Validate immutable role/image/name contract.
    c, h = data['Config'], data['HostConfig']
    uid = {'coding':65532,'qa':65531,'controller':65530}[role]
    conditions = [data['Name'] == '/'+name, c['Image'] == image,
        c['User'] == f'{uid}:{uid}', c['WorkingDir'] == '/workspace',
        c['Entrypoint'] == (['python3','-I','/opt/worker_entry.py'] if role != 'controller' else ['python3','/opt/controller/rehearsal.py']),
        not c.get('Cmd'), h['ReadonlyRootfs'], not h['Privileged'],
        h['NetworkMode'] == 'none', h.get('CgroupnsMode') == 'private', h['Runtime'] == 'runsc', h['IpcMode'] == 'none',
        h.get('PidMode', '') == '', h.get('UTSMode', '') == '', h.get('UsernsMode', '') == '',
        h['CapDrop'] == ['ALL'], not h.get('CapAdd'),
        h['SecurityOpt'] == ['no-new-privileges'], h['PidsLimit'] == 128,
        h['Memory'] == 2147483648, h['MemorySwap'] == 2147483648,
        h['NanoCpus'] == 1000000000, not h.get('Binds'), not h.get('Devices'),
        not h.get('DeviceRequests'), not data.get('Mounts'),
        not h.get('ExtraHosts'), not h.get('Dns'), not h.get('VolumesFrom'),
        h.get('LogConfig',{}).get('Type') == 'none',
        c.get('Volumes') in (None, {}),
        h['Tmpfs'] == {'/workspace':f'rw,nosuid,nodev,size=256m,uid={uid},gid={uid},mode=0700',
                       '/tmp':f'rw,noexec,nosuid,nodev,size=64m,uid={uid},gid={uid},mode=0700'},
        {(u['Name'],u['Soft'],u['Hard']) for u in h['Ulimits']} == {('fsize',8388608,8388608),('nofile',256,256)},
        not h.get('PublishAllPorts'), not h.get('PortBindings'), not h.get('Links'),
        not h.get('CgroupParent'),
        h.get('RestartPolicy',{}).get('Name','no') in ('no',''),
        h.get('RestartPolicy',{}).get('MaximumRetryCount',0) == 0]
    env = dict(item.split('=',1) for item in c['Env'])
    proxies = {'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY','http_proxy','https_proxy','all_proxy','no_proxy'}
    conditions += [all(not env.get(k) for k in proxies)]
    allowed = proxies | {'PATH','LANG','PYTHON_VERSION','PYTHON_SHA256','GPG_KEY','FC_ROLE','HOME','PLAYWRIGHT_BROWSERS_PATH'}
    conditions += [env.get('PLAYWRIGHT_BROWSERS_PATH','/opt/browsers') == '/opt/browsers',set(env) <= allowed, env.get('FC_ROLE') == role, env.get('HOME') == '/tmp']
    if not all(conditions):
        raise ValueError('Effective sandbox policy rejected')
    return True


class ContainerRuntime:
    def run(self, role, image, request, *, cancelled=lambda:False, timeout=2400):
        if not 0 < timeout <= 2400:
            raise ValueError('40 minute maximum')
        name = 'fc54-'+uuid.uuid4().hex
        start = time.monotonic()
        try:
            # Docker client defaults may inject proxy vars; inspect catches that.
            subprocess.run(specification(role,image,name),check=True,capture_output=True,timeout=min(timeout,180))
            inspected = json.loads(docker('inspect',name).stdout)[0]
            validate_inspection(inspected,role,image,name)
            remaining = timeout-(time.monotonic()-start)
            if remaining <= 0 or cancelled():
                raise RuntimeError('Cancelled before start')
            result = Supervisor().run([*DOCKER,'start','--attach','--interactive',name],
                cwd=ROOT,stdin=canonical(request),cancelled=cancelled,timeout=remaining)
            if result['code'] or result['reason']:
                raise RuntimeError('Worker failed, crashed, exceeded output or cancelled')
            return json.loads(result['stdout'])
        finally:
            # cgroup removal kills even detached setsid descendants. Failure
            # retains ledger reservation; never attest termination on uncertainty.
            try:
                docker('rm','--force',name,timeout=15)
            finally:
                inventory = docker('ps','-aq','--filter','name=^/'+name+'$',timeout=15)
                if inventory.stdout.strip():
                    raise RuntimeError('Termination unverified; fence task and retain funds')


class ContainerQA:
    """Separate QA image, UID, fresh tmpfs per check and exact artifact binding."""
    def __init__(self, image, policy='fixture', synthetic=True, runtime=None):
        if policy not in ('fixture','MZKZxyz/fort-custer-server','MZKZxyz/fort-custer-client') or synthetic != (policy=='fixture'):
            raise ValueError('Trusted repository QA policy required')
        self.image,self.policy,self.synthetic = image,policy,synthetic
        self.runtime = runtime or ContainerRuntime()
        self.checks = (('isolated-suite', ('policy',policy)),)

    def run(self, root, command):
        return self.run_exact(root,command,'0'*40,'0'*40)

    def run_exact(self, root, command, source, candidate):
        sha(source); sha(candidate)
        if tuple(command) != ('policy',self.policy):
            raise ValueError('Issue commands are never trusted policy')
        files = source_files(root)
        modes = source_modes(root)
        artifact = artifact_digest(files,modes)
        # Outer IndependentQA binds the exact candidate commit. This digest
        # verifies the actual exported tree across the process boundary.
        request = dict(files=files,modes=modes,artifact=artifact,source=source,candidate=candidate,policy=self.policy)
        r = self.runtime.run('qa',self.image,request)
        if r.get('artifact') != artifact or r.get('policy') != self.policy or r.get('source') != source or r.get('candidate') != candidate:
            raise ValueError('QA artifact mismatch')
        tests = r.get('tests',[])
        passed = bool(tests) and all(t.get('status')=='passed' and t.get('exit_code') == 0 for t in tests)
        return dict(status='passed' if passed else 'failed', command=list(command),
                    output=tree_digest(r), artifact_sha256=artifact, checks=tests,
                    identity='qa:container:65531',image=self.image)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action', choices=('lint','build','build-node-qa','rehearse'))
    args=parser.parse_args()
    if args.action=='lint':
        lock=json.loads((ROOT/'infra/images.lock.json').read_text())
        for image in lock.values():
            if not IMAGE.fullmatch(image): raise ValueError('Unpinned build base')
        runtime=json.loads((ROOT/'infra/runtime.lock.json').read_text())
        if not re.fullmatch('[a-f0-9]{64}',runtime['sha256']) or '/latest/' in runtime['url'] or runtime['version'] not in ('release-20260413.0',):
            raise ValueError('Reviewed pinned runtime required')
        try: require_live()
        except RuntimeError: pass
        else: raise ValueError('Live gate weakened')
        print('Pinned image inputs and live gate validated')
    elif args.action=='build':
        lock=json.loads((ROOT/'infra/images.lock.json').read_text())
        for role in ('controller','coding','qa'):
            docker('build','--network=none','--build-arg','BASE='+lock['python'],
                   '--build-arg','WORKER_BASE='+lock['python_worker'],'--target',role,'--file',str(ROOT/'infra/Dockerfile'),
                   '--tag','fc54-'+role+':rehearsal',str(ROOT),timeout=600)
        print('Built controller, coding and independent QA images')
    elif args.action=='build-node-qa':
        lock=json.loads((ROOT/'infra/images.lock.json').read_text())
        docker('build','--network=none','--build-arg','PYTHON_BASE='+lock['python'],
               '--build-arg','NODE_BASE='+lock['node'],'--file',str(ROOT/'infra/Dockerfile.qa-node'),
               '--tag','fc54-qa-node:prepared',str(ROOT),timeout=600)
        print('Built offline Node QA image; run full exact-SHA repository suite before activation')
    else:
        from deployment_rehearsal import rehearse
        print(json.dumps(rehearse(),indent=2))

if __name__ == '__main__':
    main()
