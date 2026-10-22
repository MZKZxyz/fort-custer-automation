"""Independent trusted evidence gate. No coding-worker supplied approvals."""
import hashlib
import json
from pathlib import PurePosixPath

RISKS = ('security', 'data', 'api', 'gameplay', 'release')
PROTECTED = ('.github/', 'config/', 'infra/', 'migrations/', 'src/qa.py', 'src/execution.py', 'AGENTS.md')


def diff_digest(diff):
    return hashlib.sha256(diff.encode()).hexdigest()


class QAController:
    def __init__(self, controller, identity='qa:mock'):
        if identity != 'qa:mock':
            raise ValueError('Only separate synthetic QA identity supported')
        self.controller, self.identity = controller, identity

    def evaluate(self, task, sha, diff, files, allowed, evidence, review, applicable=('api',)):
        # Inputs must originate in trusted QA infrastructure, not worker output.
        reasons = []
        digest = diff_digest(diff)
        if not files or not diff:
            reasons.append('missing complete diff')
        for name in files:
            p = PurePosixPath(name)
            if p.is_absolute() or '..' in p.parts or '\\' in name or name not in allowed:
                reasons.append('changed-file allowlist')
            if name.startswith(PROTECTED) or any(part.startswith('.env') for part in p.parts):
                reasons.append('protected file')
        sensitive = ('secret', 'password', 'mongodb', 'railway', 'vercel', 'auth', 'reward', 'score', 'payment', 'database')
        if any(term in (diff + ' '.join(files)).lower() for term in sensitive):
            reasons.append('sensitive change requires human security review')
        required = {'unit', 'build', *applicable}
        for check in required:
            e = evidence.get(check, {})
            if e.get('sha') != sha or e.get('identity') != self.identity or e.get('status') != 'passed' or e.get('diff') != digest:
                reasons.append('missing, stale or failing '+check)
        if (review.get('identity') != self.identity or review.get('sha') != sha or review.get('diff') != digest
                or review.get('files') != sorted(files) or review.get('decision') != 'approve'
                or set(review.get('risks', {})) != set(RISKS)
                or any(not isinstance(v, str) or not v for v in review.get('risks', {}).values())):
            reasons.append('independent complete review missing')
        result = dict(sha=sha, diff=digest, approved=not reasons, reasons=reasons, identity=self.identity)
        with self.controller.tx() as db:
            t = db.execute('SELECT * FROM execution_tasks WHERE id=?', (task,)).fetchone()
            if t['state'] != 'qa' or t['candidate'] != sha:
                raise ValueError('Candidate state/SHA mismatch')
            db.execute('UPDATE execution_tasks SET qa=?,state=? WHERE id=?', (json.dumps(result), 'pr_ready' if not reasons else 'failed', task))
            self.controller.event(db, task, 'qa_decision', **result)
        return result


class MockGitHub:
    """Transactional mock PR outbox; no GitHub client or push capability."""
    def draft(self, controller, task, operator):
        if not operator.startswith('human:'):
            raise ValueError('Human draft approval required')
        with controller.tx() as db:
            if db.execute('SELECT stopped FROM execution_control').fetchone()[0]:
                raise ValueError('Kill switch engaged')
            t = db.execute('SELECT * FROM execution_tasks WHERE id=?', (task,)).fetchone()
            if t['pr']:
                return json.loads(t['pr'])
            if t['state'] != 'pr_ready' or not t['qa']:
                raise ValueError('QA required')
            qa = json.loads(t['qa'])
            if not qa['approved'] or qa['sha'] != t['candidate']:
                raise ValueError('Stale QA')
            result = dict(url='mock://draft/'+task, sha=t['candidate'], draft=True, operator=operator,
                          merge=False, deploy=False)
            db.execute("UPDATE execution_tasks SET state='completed',pr=? WHERE id=?", (json.dumps(result), task))
            controller.event(db, task, 'mock_draft_created', **result)
            return result
