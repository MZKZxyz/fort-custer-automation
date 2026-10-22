"""Fail-closed activation audit. Attestations are evidence, never dispatch authority.

Trust roots live outside the checkout, installed by an independent administrator.
Ed25519 signatures cover the complete canonical receipt, including artifact hashes.
The last gate is deliberately impossible in Sprint 5.5.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time
from trust import canonical, digest, require_live
from execution_modes import read_modes, MODES

ROOT = Path(__file__).resolve().parents[1]
BASE = 'bfbc4785d6e5d2e86f7fd70590cff6735f75062f'
POLICY = dict(daily_cents=1000, task_cents=300, live_concurrency=1,
              deadline_seconds=2400, retries=2, auto_merge=False, deploy=False)
GATES = {
    'controller': ('Infrastructure deployment required', ['ledger', 'backup_restore', 'service_identity', 'immutable_config', 'crash_recovery']),
    'worker': ('Infrastructure deployment required', ['vm_isolation', 'deny_egress', 'no_host_mounts', 'no_credentials', 'signed_request', 'scope', 'cleanup']),
    'watchdog': ('Independent security verification required', ['controller_crash', 'worker_crash', 'deadline', 'kill_switch', 'watchdog_failure']),
    'broker': ('Software implementation required', ['worker_auth', 'task_binding', 'allowlists', 'limits', 'cancellation', 'revocation', 'usage_provenance']),
    'billing': ('Provider capability or billing guarantee required', ['daily_hard_cap', 'task_hard_cap', 'final_cost_attribution', 'delayed_charges', 'cross_midnight']),
    'server_qa': ('Independent security verification required', ['unit', 'analyzer', 'smoke', 'integration', 'syntax', 'diff', 'protected_files', 'assets']),
    'github_apps': ('Operator credential/configuration required', ['installation', 'repository_scope', 'expiry', 'revocation', 'separate_identities', 'ambiguous_response']),
    'operator_identity': ('Operator credential/configuration required', ['authenticated_dispatch', 'independent_qa', 'authenticated_publish']),
    'security_review': ('Independent security verification required', ['host', 'vm', 'broker', 'controller', 'publication']),
    'vm_provider': ('Software implementation required', ['host_service', 'guest_image', 'signature_verification', 'vsock_binding']),
    'model_transport': ('Software implementation required', ['codex_protocol', 'principal_derivation', 'bounded_transport', 'provider_cancellation']),
    'qa_assets': ('Operator credential/configuration required', ['locked_dependencies', 'native_abi', 'test_mongodb', 'reviewed_manifest']),
    'backup_restore': ('Independent security verification required', ['encrypted_offhost_backup', 'independent_restore', 'tamper_rejection', 'audit_preservation']),
    'legacy_state': ('Operator credential/configuration required', ['authoritative_ledger_inventory', 'migration_mapping', 'outstanding_holds']),
    'subscription_authentication': ('Operator credential/configuration required', ['official_login', 'entitlement', 'pinned_client', 'headless_support']),
    'subscription_no_paid_usage': ('Independent security verification required', ['paid_refills_disabled', 'no_credit_purchase', 'no_api_fallback', 'account_controls']),
    'subscription_limits': ('Independent security verification required', ['exhaustion_detection', 'unknown_failure_stop', 'independent_deadline', 'cancellation']),
}
MODE_GATES = dict(billing='api_billing', broker='api_billing', subscription_authentication='chatgpt_subscription',
                  subscription_no_paid_usage='chatgpt_subscription', subscription_limits='chatgpt_subscription')
CONFIG_HASHES = {
    'execution-modes.json': '19a5a90aa817809e51d6a289aa50979538e4d0cfc24edc547b6f3ee26a976faa',
    'policy.json': 'b7fe1204ee691061fc6b917742f080a7d8952e4799fa155675e07e81bc9658c5',
    'settings.json': '45c36fe9f4a467406d084dc5f9f9741e0b2ceada806dae4f324d227794058237',
}


def protected_file(path):
    path = Path(path)
    # Every parent must be administrator controlled, not just the leaf.
    for p in (path, *path.parents):
        s = p.lstat()
        if stat.S_ISLNK(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o022:
            raise ValueError('Trust/config path must be root owned and not writable by group/others')
    return path


def verify_receipt(gate, receipt, trust, artifacts, now, context):
    """External collector must inspect actual deployment and sign observation logs.

    A signature authenticates a collector, not the truth of an arbitrary boolean.
    Every required observation names a complete hashed log artifact. The trust
    registry pins a different externally installed verifier key for each gate.
    """
    import base64
    p = receipt['payload']
    key = protected_file(trust[gate]['public_key'])
    key_bytes = key.read_bytes()
    if hashlib.sha256(key_bytes).hexdigest() != trust[gate]['key_sha256']:
        raise ValueError('Trust key mismatch')
    if (p['gate'] != gate or p['context'] != context or p['policy'] != POLICY
            or p['synthetic'] is not False or type(p['issued']) is not int
            or type(p['expires']) is not int
            or not now - 86400 <= p['issued'] <= now < p['expires'] <= p['issued'] + 86400
            or set(p['observations']) != set(GATES[gate][1])):
        raise ValueError('Receipt binding, freshness or observation coverage rejected')
    with tempfile.TemporaryDirectory() as d:
        msg, sig = Path(d)/'message', Path(d)/'signature'
        msg.write_text(canonical(p)); sig.write_bytes(base64.b64decode(receipt['signature'], validate=True))
        subprocess.run(['openssl', 'pkeyutl', '-verify', '-pubin', '-inkey', str(key),
                        '-rawin', '-in', str(msg), '-sigfile', str(sig)],
                       check=True, capture_output=True, timeout=10)
    for observation in p['observations'].values():
        # Booleans and empty logs are never accepted as evidence.
        if not isinstance(observation, dict) or set(observation) != {'artifact', 'sha256'}:
            raise ValueError('Observation must bind a verifiable artifact')
        name = observation['artifact']
        if not isinstance(name, str) or not name or Path(name).is_absolute() or any(x in ('', '.', '..') for x in name.split('/')):
            raise ValueError('Invalid evidence path')
        artifact = artifacts/name
        if any(x.is_symlink() for x in (artifact, *artifact.parents)):
            raise ValueError('Evidence symlink rejected')
        if not 0 < artifact.stat().st_size <= 8*1024*1024:
            raise ValueError('Evidence artifact size rejected')
        data = artifact.read_bytes()
        if not data or len(data) > 8*1024*1024 or hashlib.sha256(data).hexdigest() != observation['sha256']:
            raise ValueError('Missing or modified observation artifact')
    return digest(p)


def audit(evidence=None, trust_path=None, now=None, mode=None):
    now = int(time.time()) if now is None else now
    canary = json.loads((ROOT/'config/canary-target.json').read_text())
    try:
        execution_config, selected = read_modes(ROOT, mode)
        mode_error = None
    except (OSError, ValueError, TypeError):
        execution_config, selected, mode_error = None, None, 'Missing, invalid or weakened execution mode configuration'
    context = dict(automation_base=BASE, source=canary['source_commit'], tree=canary['source_tree'],
                   canary=digest(canary), execution_mode=selected, execution_config=digest(execution_config), software=digest({
                       str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                       for folder in ('src', 'infra', 'config') for p in sorted((ROOT/folder).rglob('*'))
                       if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}))
    trust = {}
    trust_error = 'External trust registry not configured'
    if trust_path:
        try:
            trust = json.loads(protected_file(trust_path).read_text())
            trust_error = None
        except (OSError, ValueError):
            trust_error = 'External trust registry is missing or not protected'
    try:
        policy_ok = all(hashlib.sha256((ROOT/'config'/name).read_bytes()).hexdigest() == expected
                        for name, expected in CONFIG_HASHES.items())
    except OSError:
        policy_ok = False
    checks = [dict(id='policy_integrity', mandatory=True, category='Independent security verification required',
                   status='verified' if policy_ok else 'blocked',
                   reason='Configuration matches reviewed unchanged spending/security policy' if policy_ok else 'Spending/security configuration drift')]
    checks.append(dict(id='execution_configuration', mandatory=True, category='Operator credential/configuration required',
                       status='blocked' if mode_error else 'verified', reason=mode_error or 'Both reviewed execution modes disabled; no automatic switch'))
    for gate, (category, observations) in GATES.items():
        result = dict(id=gate, mandatory=True, category=category, status='blocked', required_observations=observations)
        if gate in MODE_GATES:
            result['execution_mode'] = MODE_GATES[gate]
            if selected is not None and MODE_GATES[gate] != selected:
                result.update(mandatory=False, status='not_applicable', reason='Required for the other execution mode; not satisfied or waived')
                checks.append(result)
                continue
        try:
            if trust_error:
                raise ValueError(trust_error)
            if not evidence:
                raise ValueError('Deployment receipt directory not configured')
            receipt = json.loads((Path(evidence)/(gate+'.json')).read_text())
            result['receipt_sha256'] = verify_receipt(gate, receipt, trust, Path(evidence)/'artifacts', now, context)
            result['status'] = 'verified'
        except (OSError, KeyError, TypeError, ValueError, subprocess.SubprocessError):
            result['reason'] = trust_error or 'Missing, forged, stale, incomplete or mismatched deployment evidence'
        checks.append(result)
    if selected == 'chatgpt_subscription' or mode_error:
        checks.append(dict(id='subscription_transport', mandatory=True, category='Software implementation required',
                           status='blocked', reason='Official subscription execution is not integrated with credential-free isolated workers; custom broker is unsupported and token forwarding is prohibited'))
    # No signed evidence, config or CLI option can override this code gate.
    try:
        require_live()
    except RuntimeError as exc:
        checks.append(dict(id='activation_release', mandatory=True, category='Software implementation required',
                           status='blocked', reason=str(exc)))
    else:
        checks.append(dict(id='activation_release', mandatory=True, category='Independent security verification required',
                           status='blocked', reason='Live gate changed; release requires separate review'))
    return dict(schema=2, ready=False, live_execution=False, execution_mode=selected,
                api_financial_policy_applies=selected == 'api_billing', subscription_usage_is_billing=False,
                execution_config=execution_config, context=context, policy=POLICY, checks=checks)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['check'])
    parser.add_argument('--evidence', type=Path)
    parser.add_argument('--trust', type=Path)
    parser.add_argument('--mode', choices=MODES, help='Audit one mode explicitly; never enables execution or automatic fallback')
    args = parser.parse_args()
    report = audit(args.evidence, args.trust, mode=args.mode)
    print(json.dumps(report, indent=2))
    return 1 if any(c['mandatory'] and c['status'] != 'verified' for c in report['checks']) else 0


if __name__ == '__main__':
    raise SystemExit(main())
