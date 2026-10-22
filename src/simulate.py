"""Offline reproducible exercise; never opens the operator's planning database."""
import argparse
import json
from pathlib import Path
import tempfile
from execution import Controller
from workers import MockWorker
from qa import QAController, MockGitHub, RISKS, diff_digest


def run():
    with tempfile.TemporaryDirectory() as directory:
        clock = [1792670400]
        path = Path(directory)/'simulation.db'
        c = Controller(path, lambda:clock[0])
        worker = MockWorker()
        actions = []
        def denied(label, action):
            try:
                action()
            except ValueError as error:
                actions.append(f'{label}: BLOCKED ({error})')
            else:
                raise AssertionError(label+' unexpectedly allowed')
        for i in range(7): c.add(str(i),'synthetic/client','main','area'+str(i))
        ids=[]
        for i in range(3):
            e=c.reserve(str(i),'dispatch'+str(i),200); ids.append(e)
            c.dispatch(e,'human:synthetic-operator'); worker.run(c,e)
        actions.append('Three independent workers running concurrently')
        denied('Fourth admission',lambda:c.reserve('3','fourth',200))
        assert c.dispatch(ids[0],'human:synthetic-operator') == ids[0]
        actions.append('Duplicate dispatch returned original execution ID')
        c=Controller(path,lambda:clock[0]); actions.append('Process restart restored all three active leases')
        for i in (0,1):
            c.settle(ids[i],'synthetic-receipt-'+str(i),75); c.finish(ids[i],'a'*40)
            diff='+ harmless fixture' if i==0 else '+ mongodb password'
            files=['src/fixture.py']; digest=diff_digest(diff)
            evidence={k:dict(identity='qa:mock',sha='a'*40,status='passed',diff=digest) for k in ('unit','build','api')}
            review=dict(identity='qa:mock',sha='a'*40,diff=digest,files=files,decision='approve',risks={r:'Synthetic review completed' for r in RISKS})
            QAController(c).evaluate(str(i),'a'*40,diff,files,files,evidence,review)
        MockGitHub().draft(c,'0','human:synthetic-operator')
        clock[0]+=61; c.recover()
        denied('Crash retry before accounting',lambda:c.reserve('2','retry',200))
        c.settle(ids[2],None,None)
        actions.append('Missing metering retained reservation and blocked admission')
        c.settle(ids[2],'synthetic-crash-receipt',50); c.finish(ids[2])
        retry=c.reserve('2','retry',200); c.dispatch(retry,'human:synthetic-operator'); worker.run(c,retry)
        c.recover(kill=True)
        denied('Kill switch admission',lambda:c.reserve('4','after-stop',100))
        ledger=c.snapshot()
        lines=['# Sprint 5.2 synthetic execution report','',
               '**No Codex calls, billed usage, pushes, deployments or live draft PRs.**','',
               '## Scenarios','']+['- '+a for a in actions]
        lines+=['','## Final ledger','','| Task | State | QA | Draft |','|---|---|---|---|']
        for t in ledger['execution_tasks']:
            qa=json.loads(t['qa']) if t['qa'] else None
            lines.append(f"| {t['id']} | {t['state']} | {qa['reasons'] if qa else 'pending'} | {'mock draft' if t['pr'] else 'none'} |")
        lines+=['','## Accounting','','Amounts below are synthetic cents, not actual billed dollars.','',
                '| Attempt task | Reserved | Synthetic settled | Held |','|---|---|---|---|']
        for a in ledger['execution_attempts']:
            lines.append(f"| {a['task']} | {a['reserved']} | {a['actual']} | {0 if a['settled'] else a['reserved']} |")
        lines+=['','## Human actions required','',
                '- Confirm termination and reconcile the interrupted retry; its reservation remains held.',
                '- Review the sensitive QA failure and the simulated draft.',
                '- Separately authorize a future one-agent canary after external billing and sandbox enforcement exist.',
                '- Merge and production deployment remain outside this controller.','']
        return '\n'.join(lines)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--out',default='examples/sprint-5.2-report.md')
    args=parser.parse_args(); Path(args.out).write_text(run())
