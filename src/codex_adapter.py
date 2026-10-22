"""Official CLI integration and external sandbox launch specification.

run() is intentionally blocked until hard billing/isolation can be established.
Supervisor is independently testable with harmless local processes; no Codex
invocation occurs in tests. OS sandbox enforcement is external to the model.
"""
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
from trust import require_live
from independent_qa import export


class Supervisor:
    """Bounded process group; external container watchdog is also mandatory.

    A process group alone is insufficient against a hostile setsid() child.
    Container/cgroup termination must be verified before releasing the lease.
    """
    def run(self, command, *, cwd, stdin='', cancelled=lambda:False, timeout=2400):
        if not 0<timeout<=2400:
            raise ValueError('40-minute hard ceiling')
        env={'PATH':'/usr/bin:/bin','HOME':'/nonexistent','LANG':'C.UTF-8'}
        start=time.monotonic()
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err, tempfile.TemporaryFile() as inp:
            inp.write(stdin.encode()); inp.seek(0)
            process=subprocess.Popen(command,cwd=cwd,env=env,stdin=inp,stdout=out,stderr=err,start_new_session=True)
            reason=None
            try:
                while process.poll() is None:
                    if cancelled() or time.monotonic()-start>=timeout:
                        reason='cancelled' if time.monotonic()-start<timeout else 'timeout'
                        break
                    if out.tell()+err.tell()>8*1024*1024:
                        reason='output_limit'; break
                    time.sleep(.02)
            finally:
                # Always reap lingering children, including after parent exit.
                try: os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError: pass
                process.wait(timeout=5)
            out.seek(0); err.seek(0)
            stdout=out.read(8*1024*1024); stderr=err.read(8*1024*1024)
        return dict(code=process.returncode,reason=reason,stdout=stdout,stderr=stderr)


class ContainerSupervisor:
    """Kill/remove named container, then verify daemon inventory before success.

    Host process-tree cancellation is supplementary. A separate host watchdog
    must enforce the deadline if this controller process dies.
    """
    def run(self, launch, *, cwd, name, stdin='', cancelled=lambda:False, timeout=2400):
        if not re.fullmatch(r'fc-[a-f0-9]{32}',name):
            raise ValueError('Invalid durable container name')
        env={'PATH':'/usr/bin:/bin','HOME':'/nonexistent'}
        try:
            result=Supervisor().run(launch,cwd=cwd,stdin=stdin,cancelled=cancelled,timeout=timeout)
        finally:
            subprocess.run(['docker','rm','--force',name],env=env,capture_output=True,timeout=15)
            inventory=subprocess.run(['docker','ps','--all','--quiet','--filter','name=^/'+name+'$'],
                                     env=env,capture_output=True,timeout=15)
            if inventory.returncode or inventory.stdout.strip():
                raise RuntimeError('Container termination unverifiable; retain reservation and lease fence')
        return result


class CodexAdapter:
    @staticmethod
    def command(model):
        if not re.fullmatch(r'[a-zA-Z0-9._-]+',model):
            raise ValueError('Pinned model identity required')
        return ('codex','exec','--json','--ephemeral','--ignore-user-config','--ignore-rules',
                '--skip-git-repo-check','--model',model,'--sandbox','workspace-write',
                '--config','sandbox_workspace_write.network_access=false','-')

    @staticmethod
    def sandbox(image, workspace, name, command):
        if not re.fullmatch(r'[a-z0-9./_-]+@sha256:[0-9a-f]{64}',image) or not re.fullmatch(r'fc-[a-f0-9]{32}',name):
            raise ValueError('Pinned sandbox image and durable container identity required')
        workspace=Path(workspace).resolve()
        if not workspace.is_dir() or ',' in str(workspace):
            raise ValueError('Disposable workspace required')
        return ('docker','run','--rm','--name',name,'--runtime=runsc','--network=none',
                '--read-only','--user=65532:65532','--cap-drop=ALL','--security-opt=no-new-privileges',
                '--pids-limit=128','--memory=2g','--cpus=1','--ulimit','fsize=16777216:16777216',
                '--tmpfs','/tmp:rw,noexec,nosuid,size=128m',
                '--tmpfs','/home/agent:rw,noexec,nosuid,size=32m',
                '--env','HOME=/home/agent','--env','CODEX_HOME=/home/agent/.codex',
                '--mount',f'type=bind,src={workspace},dst=/workspace',
                '--workdir','/workspace',image,*command)

    def checkout(self, mirror, source, root):
        directory=Path(tempfile.mkdtemp(prefix='codex-',dir=root))
        # Export exact tree, no controller .git, credentials, refs, hooks or config.
        export(mirror,source,directory)
        return directory

    def run(self, ledger, execution, mirror, root, image, model, prompt):
        require_live()
        # Dormant integration: removing the activation gate requires review of
        # hard billing, credential-free transport and external watchdog evidence.
        with ledger.tx() as db:
            row=ledger.get(db,execution)
            spec=__import__('json').loads(row['spec'])
        ledger.validate_spec(spec)
        directory=self.checkout(mirror,spec['source'],root)
        name='fc-'+execution
        launch=self.sandbox(image,directory,name,self.command(model))
        ledger.claim(execution,'coding:'+execution)
        last_beat=[0.0]
        def cancelled():
            try:
                if time.monotonic()-last_beat[0]>10:
                    ledger.heartbeat(execution,'coding:'+execution)
                    last_beat[0]=time.monotonic()
                with ledger.tx() as db:
                    row=ledger.get(db,execution)
                    stopped=db.execute('SELECT stopped FROM s53_control').fetchone()[0]
                return bool(stopped) or row['state']!='running'
            except Exception:
                return True
        remaining=row['deadline']-ledger.clock()
        if remaining<=0:
            ledger.stop(run=execution)
            raise RuntimeError('Original dispatch deadline expired before launch')
        result=ContainerSupervisor().run(launch,cwd=directory,name=name,stdin=prompt,
                                         cancelled=cancelled,timeout=min(2400,remaining))
        ledger.terminated(execution)
        if result['code'] or result['reason']:
            ledger.stop(run=execution)
            raise RuntimeError('Codex failed/cancelled; metering reconciliation required')
        from metering import parse_events
        observed=parse_events(result['stdout'].decode().splitlines(),execution,model)
        # Return telemetry to a trusted collector; never ingest agent-supplied
        # cost files or directly finalize billing from token counts.
        return dict(workspace=str(directory),usage=observed)


class SandboxTests:
    """Real QA sandbox contract, separate image/identity from the coding sandbox.

    Prebuilt QA image must contain Node 24, pinned npm dependencies and a
    checksum-verified mongod with MONGOD_BINARY configured inside the image.
    No npm install, production DB or network is required at test time.
    """
    synthetic=False
    def __init__(self,image):
        from independent_qa import SERVER_CHECKS
        self.image=image
        self.checks=SERVER_CHECKS

    def checks_for(self, root):
        # Production and tool JS syntax, with no repository package scripts.
        syntax=tuple(('syntax:'+str(p.relative_to(root)),('node','--check',str(p.relative_to(root))))
                     for p in sorted(root.rglob('*.js')))
        return self.checks+syntax

    def run(self, root, command):
        import hashlib
        import uuid
        name='fc-'+uuid.uuid4().hex
        launch=CodexAdapter.sandbox(self.image,root,name,command)
        # Use a short QA timeout; worker supervisor and QA must run as distinct
        # OS services. Container watchdog/absence attestation required in deployment.
        result=ContainerSupervisor().run(launch,cwd=root,name=name,timeout=180)
        return dict(status='passed' if result['code']==0 and not result['reason'] else 'failed',
                    command=list(command),output=hashlib.sha256(result['stdout']+result['stderr']).hexdigest())
