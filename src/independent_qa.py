"""Fresh-checkout QA; control-plane code never imports candidate Python/JS.

Full diff and test evidence are generated here, then a distinct review service
attests risk decisions. No worker-produced test/review files are accepted.
"""
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import tempfile
import io
from trust import canonical, digest, sha

PROTECTED = ('.github', '.git', 'config', 'infra', 'migrations', 'AGENTS.md',
             'src/execution.py', 'src/qa.py', 'src/trust.py', 'src/secure_ledger.py',
             'src/independent_qa.py', 'src/codex_adapter.py', 'src/publication.py')
RISKS = ('security','api','data','gameplay','deployment')
SERVER_CHECKS = (
    ('analyzer', ('node','--test','test/analyzer.test.js')),
    ('server', ('node','--test')),
    ('smoke', ('node','tools/maze-analyzer/cli.js','--seed','sprint4-0')),
)


def safe_path(name):
    return isinstance(name,str) and bool(name) and not name.startswith('/') and '\\' not in name and all(p not in ('','.','..') for p in name.split('/')) and '\x00' not in name


def protected(name):
    return any(name==p or name.startswith(p+'/') for p in PROTECTED) or any(p.startswith('.env') or p in ('AGENTS.md','.codex','.git') for p in PurePosixPath(name).parts)


def git(repo, *args):
    # repo must be a trusted bare ingestion mirror; never point this at worker .git.
    return subprocess.check_output(['git','-c','core.hooksPath=/dev/null','-c','core.fsmonitor=false',
                                   '-c','diff.external=','-C',str(repo),*args],
                                  env={'PATH':'/usr/bin:/bin','HOME':'/nonexistent','GIT_CONFIG_NOSYSTEM':'1',
                                       'GIT_CONFIG_GLOBAL':'/dev/null','GIT_NO_REPLACE_OBJECTS':'1'},timeout=30)


def export(repo, commit, destination):
    sha(commit)
    data=git(repo,'archive','--format=tar',commit)
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        members=archive.getmembers()
        for member in members:
            if not safe_path(member.name.rstrip('/')) or not (member.isfile() or member.isdir()) or member.name=='.git' or member.name.startswith('.git/'):
                raise ValueError('Unsafe candidate archive (links/devices prohibited)')
        archive.extractall(destination, members=members, filter='data')


class IndependentQA:
    def __init__(self, ledger, runner, reviewer):
        self.ledger, self.runner, self.reviewer=ledger,runner,reviewer

    def inspect(self, run, mirror):
        with self.ledger.tx() as db:
            r=self.ledger.get(db,run)
            if r['state']!='qa':
                raise ValueError('Candidate not ready')
        spec=json.loads(r['spec']); source,candidate=spec['source'],sha(r['candidate'])
        git(mirror,'merge-base','--is-ancestor',source,candidate)
        diff=git(mirror,'diff','--no-ext-diff','--no-textconv','--binary','--full-index','--no-renames',source,candidate,'--')
        names=git(mirror,'diff','--no-ext-diff','--no-textconv','--name-only','-z','--no-renames',source,candidate,'--').decode().split('\0')[:-1]
        reasons=[]
        if not diff or not names:
            reasons.append('Missing complete diff')
        if any(not safe_path(p) or protected(p) or p not in spec['allowed'] for p in names):
            reasons.append('Changed-file or protected-file policy')
        # Modes are part of the complete binary diff; archive rejects links, too.
        if b'new file mode 120000' in diff or b'new file mode 160000' in diff:
            reasons.append('Symlink or submodule')
        tests=[]
        if not reasons:
            with tempfile.TemporaryDirectory(prefix='independent-qa-') as root:
                export(mirror,candidate,root)
                if self.runner.synthetic != self.ledger.synthetic:
                    raise ValueError('QA provenance mismatch')
                checks=self.runner.checks_for(Path(root)) if hasattr(self.runner,'checks_for') else self.runner.checks
                for name,command in checks:
                    tests.append(dict(name=name,sha=candidate,**self.runner.run(Path(root),command)))
                if not tests or any(t['status']!='passed' for t in tests):
                    reasons.append('Required tests failed or missing')
        report=dict(run=run,task=spec['task'],source=source,candidate=candidate,
                    diff=hashlib.sha256(diff).hexdigest(),files=sorted(names),tests=tests,
                    reasons=reasons,synthetic=self.ledger.synthetic,policy='sprint-5.3-v1')
        # The reviewer receives every byte, including binary changes, and the exact test report.
        with self.ledger.tx() as db:
            db.execute('INSERT OR IGNORE INTO s53_qa_reports VALUES (?,?)',(digest(report),canonical(report)))
        return report,diff

    def accept(self, run, report, review_grant):
        with self.ledger.tx() as db:
            self.ledger.enabled(db)
            stored=db.execute('SELECT report FROM s53_qa_reports WHERE digest=?',(digest(report),)).fetchone()
            if not stored or stored[0]!=canonical(report):
                raise ValueError('Untrusted QA report')
            r=self.ledger.get(db,run)
            if r['state']!='qa' or r['candidate']!=report['candidate'] or report['run']!=run or report['reasons']:
                raise ValueError('Failed or stale QA')
            if not report['tests'] or any(t['sha']!=r['candidate'] or t['status']!='passed' for t in report['tests']):
                raise ValueError('Missing exact-SHA test evidence')
            risks=review_grant.get('payload',{}).get('binding',{}).get('risks',{})
            if set(risks)!=set(RISKS) or any(v!='approved' for v in risks.values()):
                raise ValueError('Independent risk review required')
            binding=dict(run=run,report=digest(report),risks=risks)
            reviewer=self.reviewer.consume(db,review_grant,'qa',binding,self.ledger.clock())
            result=dict(report=report,digest=digest(report),reviewer=reviewer)
            db.execute("UPDATE s53_runs SET state='pr_ready',qa=? WHERE id=?",(canonical(result),run))
            self.ledger.event(db,run,'independent_qa_approved',result)
            return result
