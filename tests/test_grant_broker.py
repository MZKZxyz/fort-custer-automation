"""Offline broker/transport security fixtures; no real model or GitHub writes."""
import array
from concurrent.futures import ProcessPoolExecutor
import copy
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import test_concurrency_coordinator as cf
from src import grant_broker as b, worker_handoff as wire, worker_transport as t
from src import orchestration_evidence as e, integration_control as control

REAL_GATE = control.block_live_dispatch


def claimant(config, policy, execution, task, now):
    try: return b.Broker(config, lambda:now).claim_synthetic(policy, execution, task, 'race')['token']
    except ValueError: return None


def crash_after_start(config, claim, now):
    b.Broker(config, lambda:now).start_synthetic(claim)
    os._exit(19)


class Fixture:
    def __init__(self):
        self.f = cf.Fixture(count=1)
        self.config = dict(self.f.config, schema=b.PROTOCOL, slots=1,
                           ledger=str(self.f.root/'broker.sqlite'))
        self.broker = b.Broker(self.config, lambda:self.f.now)
        self.broker.initialize()
        self.controller = self.f.fixtures[0]

    def close(self): self.f.close()
    def claim(self):
        return self.broker.claim_synthetic(self.f.policies[0], self.f.approvals[0]['id'], 'task-0', 'mock')
    def output(self, req):
        a = self.broker.inspect()['tasks'][self.f.approvals[0]['id']]['authorization']
        source = self.controller.config['repositories'][a['spec']['repo']]['source']
        return wire.response(req, {name: (0o644, (Path(source)/name).read_bytes()+b'\n// broker fixture\n')
                                   for name in a['allowed']})


class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(); self.addCleanup(self.f.close)
        self.b = self.f.broker

    def test_process_race_and_restart_single_durable_claim(self):
        args = (self.f.config, str(self.f.f.policies[0]), self.f.f.approvals[0]['id'], 'task-0', self.f.f.now)
        with ProcessPoolExecutor(4, mp_context=multiprocessing.get_context('fork')) as pool:
            results = list(pool.map(claimant, *[[v]*4 for v in args]))
        self.assertEqual(sum(v is not None for v in results), 1)
        restarted = b.Broker(self.f.config, lambda:self.f.f.now)
        self.assertEqual(restarted.inspect()['active'], 1)
        with self.assertRaises(ValueError): self.f.claim()
        with self.assertRaises(FileExistsError): restarted.initialize()

    def test_advancing_wall_clock_preserves_claim_event_identity(self):
        import itertools
        ticks = itertools.count()
        self.b.clock = lambda:self.f.f.now+next(ticks)/1000
        c = self.f.claim()
        row = self.b.inspect()['tasks'][c['execution']]
        self.assertEqual(row['events'][0]['at'], c['started'])
        self.b.start_synthetic(c)

    def test_existing_ledgers_and_policy_unchanged(self):
        paths = [self.f.controller.path, Path(self.f.controller.config['state'])/'local.sqlite', self.f.f.coordinator.path]
        before = [p.read_bytes() for p in paths]
        self.f.claim()
        self.assertEqual(before, [p.read_bytes() for p in paths])
        self.assertEqual(self.f.controller.runner.inspect(self.f.f.approvals[0]['id'])['state'], 'approved')

    def test_duplicate_and_advisory_authorizations_rejected(self):
        for doc in ({'proposal':'preview'}, {'promotion':'receipt'}, {'orchestration':'preview'}):
            with self.assertRaises((ValueError, TypeError)):
                self.b.claim_synthetic(doc, 'missing', 'task-0', 'mock')
        self.f.claim()
        with self.assertRaises(ValueError): self.f.claim()

    def test_pending_approval_not_consumed(self):
        f = self.f.controller
        with f.runner.tx() as db:
            r = f.runner.read(db, self.f.f.approvals[0]['id'])
            r['state'] = 'pending'; r['history'] = r['history'][:1]; f.runner.save(db, r)
        with self.assertRaises(ValueError): self.f.claim()
        self.assertEqual(self.b.inspect()['active'], 0)

    def test_startup_crash_restart_no_relaunch(self):
        c = self.f.claim(); req = self.b.start_synthetic(c)
        self.assertNotIn(b'policy_path', req)
        other = b.Broker(self.f.config, lambda:self.f.f.now)
        with self.assertRaises(ValueError): other.start_synthetic(c)
        with self.assertRaises(ValueError): self.f.claim()
        other.hold(c, 'lost startup response')
        with self.assertRaises(ValueError): other.start_synthetic(c)

    def test_pre_assignment_crash_remains_owned(self):
        self.f.claim()
        self.assertEqual(b.Broker(self.f.config).inspect()['active'], 1)
        with self.assertRaises(ValueError): self.f.claim()

    def test_process_death_after_startup_intent_cannot_replay(self):
        c = self.f.claim()
        process = multiprocessing.get_context('fork').Process(target=crash_after_start,
            args=(self.f.config, c, self.f.f.now))
        process.start(); process.join(10)
        self.assertEqual(process.exitcode, 19)
        self.assertEqual(self.b.inspect()['ambiguous'], 1)
        with self.assertRaises(ValueError): self.b.start_synthetic(c)

    def test_lost_validation_commit_retains_qa_intent(self):
        c = self.f.claim(); req = self.b.start_synthetic(c)
        self.b.capture_synthetic(c, self.f.output(req))
        event = self.b._event
        def fail(db, claim, state, doc):
            if state == 'validated': raise sqlite3.OperationalError('synthetic failed commit')
            return event(db, claim, state, doc)
        with patch.object(self.b, '_event', side_effect=fail):
            with self.assertRaises(sqlite3.OperationalError): self.b.validate_synthetic(c)
        self.assertEqual(self.b.inspect()['tasks'][c['execution']]['state'], 'checking')
        with self.assertRaises(ValueError): self.b.validate_synthetic(c)
        with self.assertRaises(ValueError): self.f.claim()

    def test_retained_artifact_tampering_rejected(self):
        c = self.f.claim(); req = self.b.start_synthetic(c)
        self.b.capture_synthetic(c, self.f.output(req))
        # A ledger owner can remove triggers; integrity_check alone cannot
        # establish semantic integrity. Validate retained response bindings too.
        with sqlite3.connect(self.b.path) as db:
            db.execute('DROP TRIGGER immutable_events_UPDATE')
            row = db.execute("SELECT seq,document FROM events WHERE state='received'").fetchone()
            doc = json.loads(row[1]); out = json.loads(doc['response']); out['token'] = 'f'*32
            doc['response'] = e.canonical(out)
            db.execute('UPDATE events SET document=? WHERE seq=?', (e.canonical(doc), row[0]))
        with self.assertRaises(ValueError): self.b.inspect()

    def test_expiry_stop_and_recovery_never_requeue(self):
        c = self.f.claim(); self.f.f.now = c['deadline']
        self.b.sweep()
        self.assertEqual(self.b.inspect()['ambiguous'], 1)
        with self.assertRaises(ValueError): self.b.start_synthetic(c)
        with self.assertRaises(ValueError): self.b.recover(c, 'operator', 'f'*64, 'yes')
        proof = e.digest({'watchdog':'fixture termination observed'})
        self.b.recover(c, 'operator', proof, 'CONFIRM TERMINATED '+e.digest(c)+' '+proof)
        self.assertEqual(self.b.inspect()['active'], 0)
        with self.assertRaises(ValueError): self.f.claim()
        with self.assertRaises(ValueError): self.b.capture_synthetic(c, b'{}')

    def test_stop_before_claim_and_each_transition(self):
        stop = Path(self.f.config['stop_files'][0]); stop.symlink_to('/missing-stop-target')
        with self.assertRaises(ValueError): self.f.claim()
        stop.unlink(); c = self.f.claim()
        stop.touch()
        with self.assertRaises(ValueError): self.b.start_synthetic(c)
        stop.unlink(); req = self.b.start_synthetic(c)
        stop.touch()
        with self.assertRaises(ValueError): self.b.capture_synthetic(c, self.f.output(req))
        stop.unlink(); self.b.capture_synthetic(c, self.f.output(req)); stop.touch()
        with self.assertRaises(ValueError): self.b.validate_synthetic(c)
        self.b.sweep(); self.assertEqual(self.b.inspect()['ambiguous'], 1)

    def test_stop_during_qa_holds_capacity(self):
        c = self.f.claim(); req = self.b.start_synthetic(c); self.b.capture_synthetic(c, self.f.output(req))
        def stop(*args, **kwargs):
            Path(self.f.config['stop_files'][0]).touch()
            raise ValueError('STOP in QA')
        with patch('src.concurrency_coordinator.verify_candidate', side_effect=stop):
            with self.assertRaises(ValueError): self.b.validate_synthetic(c)
        self.b.sweep(); self.assertEqual(self.b.inspect()['ambiguous'], 1)

    def test_stale_forged_truncated_delayed_and_replayed_completion(self):
        c = self.f.claim(); req = self.b.start_synthetic(c); out = self.f.output(req)
        for field, value in [('token','f'*32), ('generation',999), ('artifact_digest','f'*64), ('request','f'*64), ('checks', [{'argv':['sh','-c','true']}])]:
            forged = json.loads(out); forged[field] = value
            with self.assertRaises(ValueError): self.b.capture_synthetic(c, e.canonical(forged).encode())
        with self.assertRaises(ValueError): self.b.capture_synthetic(c, out[:-1])
        with self.assertRaises(ValueError): self.b.capture_synthetic(dict(c, generation=999), out)
        self.b.capture_synthetic(c, out)
        with self.assertRaises(ValueError): self.b.capture_synthetic(c, out)
        self.f.f.now = c['deadline']
        with self.assertRaises(ValueError): self.b.validate_synthetic(c)

    def test_artifact_missing_extra_symlink_and_executable_tampering(self):
        c = self.f.claim(); req = self.b.start_synthetic(c)
        name = json.loads(req)['allowed'][0]
        for files in ({'extra.js':(0o644,b'x')}, {name:(0o120777,b'x')}, {name:(0o644,b'x'),'extra.js':(0o644,b'x')}):
            with self.assertRaises(ValueError): self.b.capture_synthetic(c, wire.response(req, files))
        # Empty artifact rejected by existing safe path decoder.
        doc = json.loads(self.f.output(req)); doc['artifact'] = {}; doc['artifact_digest'] = e.digest({})
        with self.assertRaises(ValueError): self.b.capture_synthetic(c, e.canonical(doc).encode())
        self.b.capture_synthetic(c, wire.response(req, {name:(0o755,b'const x=1;')}))
        with self.assertRaisesRegex(ValueError, 'permission'): self.b.validate_synthetic(c)
        with self.assertRaises(ValueError): self.b.validate_synthetic(c)  # No uncertain QA replay.

    def test_stop_at_final_validation_rolls_back_completion(self):
        c = self.f.claim(); req = self.b.start_synthetic(c); self.b.capture_synthetic(c, self.f.output(req))
        event = self.b._event
        def stop(db, claim, state, doc):
            result = event(db, claim, state, doc)
            if state == 'validated': Path(self.f.config['stop_files'][0]).touch()
            return result
        with patch.object(self.b, '_event', side_effect=stop):
            with self.assertRaises(ValueError): self.b.validate_synthetic(c)
        self.b.sweep(); self.assertEqual(self.b.inspect()['ambiguous'], 1)

    def test_source_and_manifest_drift_rejected(self):
        c = self.f.claim()
        policy = json.loads(self.f.controller.path.read_text())
        policy['catalog']['tasks']['task-0']['input_hash'] = 'f'*64
        self.f.controller.path.write_text(json.dumps(policy))
        with self.assertRaises(ValueError): self.b.start_synthetic(c)

    def test_failed_approved_qa_never_validates(self):
        c = self.f.claim(); req = self.b.start_synthetic(c); name = json.loads(req)['allowed'][0]
        self.b.capture_synthetic(c, wire.response(req, {name:(0o644,b'const = broken!')}))
        with self.assertRaises(ValueError): self.b.validate_synthetic(c)
        self.assertEqual(self.b.inspect()['tasks'][c['execution']]['state'], 'checking')
        with self.assertRaises(ValueError): self.b.validate_synthetic(c)

    def test_live_gate_and_missing_isolation_no_override(self):
        with patch.object(control, 'block_live_dispatch', side_effect=REAL_GATE):
            with self.assertRaisesRegex(ValueError, control.PROTOCOL): self.b.dispatch_live(isolated=True)
        with self.assertRaises(ValueError): t.IsolatedEndpoint('/tmp/no-socket', os.getuid())
        with self.assertRaises(ValueError): t.IsolatedEndpoint('/tmp/no-socket', 0)
        bad = dict(self.f.config, schema='live', slots=2)
        with self.assertRaises(ValueError): b.Broker(bad)

    def test_readiness_read_only_and_always_blocked(self):
        c = self.f.claim(); self.b.hold(c, 'disconnected')
        before = self.b.path.read_bytes()
        view = control.health(self.f.controller.path, now=self.f.f.now, broker_path=self.b.path,
                              broker_config=self.f.config)
        self.assertFalse(view['live_ready']); self.assertEqual(view['broker']['ambiguous'], 1)
        self.assertEqual(self.b.path.read_bytes(), before)
        result = subprocess.run([sys.executable,'-m','src.integration_control','--policy',str(self.f.controller.path)], capture_output=True)
        self.assertEqual(result.returncode, 1)

    def test_schema_configuration_integrity_and_clock_regression(self):
        c = self.f.claim()
        self.f.f.now -= 1
        with self.assertRaises(ValueError): self.b.hold(c, 'clock regressed')
        config = dict(self.f.config, enabled=False)
        with self.assertRaises(ValueError): b.Broker(config).inspect()
        with sqlite3.connect(self.b.path) as db:
            with self.assertRaises(sqlite3.IntegrityError): db.execute('DELETE FROM grants')
            db.execute('CREATE TABLE unknown(x)')
        with self.assertRaises(ValueError): self.b.inspect()


class Endpoint:
    """Same-principal socket mock. Exercises kernel auth, never proves isolation."""
    def __init__(self, path, transform):
        self.path, self.transform, self.errors = str(path), transform, []
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(self.path); os.chmod(self.path, 0o600); self.sock.listen(1)
        self.thread = threading.Thread(target=self.run, daemon=True); self.thread.start()
    def run(self):
        try:
            self.sock.settimeout(3)
            with self.sock.accept()[0] as conn:
                req = t.receive(conn, time.monotonic()+2)
                self.transform(conn, req)
        except (OSError, ValueError) as ex: self.errors.append(type(ex).__name__)
        finally: self.sock.close()
    def close(self): self.thread.join(4); self.sock.close()


class ProcessEndpoint:
    """Credential-free subprocess mock, still the same UID, not a sandbox."""
    def __init__(self, path, source, allowed):
        self.path = str(path)
        self.work = tempfile.TemporaryDirectory()
        root = Path(self.work.name)
        for name in allowed:
            target = root/name; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((Path(source)/name).read_bytes()); target.chmod(0o644)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.bind(self.path); os.chmod(self.path, 0o600); sock.listen(1)
            script = Path(__file__).parent/'fixtures/broker/mock_worker.py'
            self.process = subprocess.Popen([sys.executable, '-I', str(script), str(sock.fileno())],
                cwd=root, env={'PATH':'/usr/bin:/bin', 'HOME':str(root), 'LANG':'C.UTF-8'},
                close_fds=True, pass_fds=(sock.fileno(),), start_new_session=True,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        finally: sock.close()
    def close(self):
        try:
            _, error = self.process.communicate(timeout=4)
            if self.process.returncode: raise AssertionError(error.decode())
        finally:
            if self.process.poll() is None: self.process.kill(); self.process.communicate()
            self.work.cleanup()


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.root.chmod(0o700)
    def endpoint(self, transform):
        ep = Endpoint(self.root/'worker.sock', transform); self.addCleanup(ep.close); return ep
    def exchange(self, ep, seconds=1): return t.exchange(ep.path, b'fixture', os.getuid(), seconds)

    def test_kernel_identity_and_exact_bytes(self):
        ep = self.endpoint(lambda s,r:t.send(s,b'answer:'+r,time.monotonic()+1))
        self.assertEqual(self.exchange(ep), b'answer:fixture')
        left, right = socket.socketpair()
        self.addCleanup(right.close)
        with left as sock:
            self.assertFalse(sock.get_inheritable())

    def test_wrong_peer_identity_before_request(self):
        ep = self.endpoint(lambda *_:self.fail('Request leaked to wrong peer'))
        with patch.object(t, 'peer_uid', return_value=os.getuid()+1):
            with self.assertRaisesRegex(ValueError,'identity'): self.exchange(ep)

    def test_truncated_oversized_and_replayed_frames(self):
        for payload in (b'\x00', struct.pack('!I', t.MAXIMUM+1), struct.pack('!I',4)+b'ab', struct.pack('!I',1)+b'xEXTRA'):
            with self.subTest(payload=payload):
                path = self.root/'worker.sock'
                if path.exists(): path.unlink()
                ep = self.endpoint(lambda s,r:s.sendall(payload))
                with self.assertRaises(ValueError): self.exchange(ep)
                ep.close()

    def test_disconnect_and_deadline_no_retry(self):
        ep = self.endpoint(lambda s,r:time.sleep(.15))
        with self.assertRaises(TimeoutError): self.exchange(ep,.03)

    def test_descriptor_transfer_rejected_and_closed(self):
        sentinel = self.root/'credential'; sentinel.write_bytes(b'fixture-secret')
        def transfer(s,r):
            with sentinel.open('rb') as file:
                s.sendmsg([struct.pack('!I',1)+b'x'], [(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[file.fileno()]))])
        ep = self.endpoint(transfer)
        with self.assertRaisesRegex(ValueError,'Descriptor'): self.exchange(ep)

    def test_unsupported_platform_and_unsafe_socket(self):
        left, right = socket.socketpair()
        self.addCleanup(right.close)
        with left as sock, patch.object(t.sys, 'platform', 'unsupported'):
            with self.assertRaisesRegex(ValueError,'Unsupported'): t.peer_uid(sock)
        p = self.root/'regular'; p.touch()
        with self.assertRaises(ValueError): t.exchange(p,b'x',os.getuid(),1)
        p.unlink(); p.symlink_to('/missing')
        with self.assertRaises((ValueError, FileNotFoundError)): t.exchange(p,b'x',os.getuid(),1)
        with self.assertRaises(ValueError): t.exchange(p,b'x'* (t.MAXIMUM+1),os.getuid(),1)


class SyntheticEndToEndTests(unittest.TestCase):
    def test_socket_claim_reconstruction_qa_and_separate_review(self):
        result = demonstration()
        self.assertEqual(result['state'], 'validated')
        self.assertFalse(result['external_isolation_proven'])
        self.assertFalse(result['publication_performed'])


def demonstration():
    f = Fixture()
    try:
        historical = Path(f.controller.config['state'])/'local.sqlite'
        before = hashlib.sha256(historical.read_bytes()).hexdigest()
        c = f.claim(); req = f.broker.start_synthetic(c)
        a = f.broker.inspect()['tasks'][c['execution']]['authorization']
        source = f.controller.config['repositories'][a['spec']['repo']]['source']
        # Deliberately inheritable sentinel must not reach the mock subprocess.
        sentinel = os.open(f.controller.path, os.O_RDONLY); os.set_inheritable(sentinel, True)
        try:
            with patch.dict(os.environ, {'GITHUB_TOKEN':'synthetic-credential-sentinel', 'SSH_AUTH_SOCK':'sentinel'}):
                ep = ProcessEndpoint(f.f.root/'worker.sock', source, a['allowed'])
        finally: os.close(sentinel)
        try: out = t.exchange(ep.path, req, os.getuid(), 2)
        finally: ep.close()
        f.broker.capture_synthetic(c, out)
        qa = f.broker.validate_synthetic(c)
        restarted = b.Broker(f.config, lambda:f.f.now)
        row = restarted.inspect()['tasks'][c['execution']]
        if before != hashlib.sha256(historical.read_bytes()).hexdigest(): raise AssertionError('History modified')
        try: f.claim()
        except ValueError: pass
        else: raise AssertionError('Duplicate claim succeeded')
        return dict(schema=b.PROTOCOL, state=row['state'], task=c['task'], source=row['authorization']['source'],
                    generation=c['generation'], qa_digest=e.digest(qa),
                    candidate=qa['candidate_manifest'], independent_qa=True,
                    authenticated_kernel_peer=True, subprocess_mock=True, inherited_environment_and_fds_checked=True,
                    external_isolation_proven=False,
                    historical_ledger_unchanged=True, real_codex_workers=0,
                    publication_review='required-separate-human-action-no-legacy-import',
                    publication_performed=False, live_dispatch=False)
    finally: f.close()


if __name__ == '__main__':
    if '--demo' in sys.argv: print(json.dumps(demonstration(), sort_keys=True, indent=2))
    else: unittest.main()
