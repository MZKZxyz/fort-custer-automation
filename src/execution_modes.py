"""Disabled execution profiles and passive official-client quota observations.

No login, auth-cache access, token forwarding, credit purchase, provider request
or fallback is implemented. Observations must originate from a future reviewed
trusted Codex collector, never worker JSON. They do not authorize execution.
"""
import json
import math
from pathlib import Path

MODES = ('chatgpt_subscription', 'api_billing')
SUBSCRIPTION = dict(live_enabled=False, authentication='official_codex_chatgpt_login',
    custom_model_broker=False, automatic_credit_purchase=False, paid_refills=False,
    api_billing_fallback=False, quota_is_per_task_cutoff=False,
    exhaustion_action='stop_and_require_operator', credential_transport='unimplemented_blocked')
API = dict(live_enabled=False, authentication='api_key_in_trusted_broker_only',
    daily_cents=1000, task_reservation_cents=300, hard_cap_guarantee_required=True,
    authoritative_reconciliation_required=True, fail_closed=True)


def validate_modes(config, selected=None):
    # Canonical serialization preserves bool/int distinctions (False != 0 in policy).
    expected = dict(schema=1, selected=config.get('selected') if isinstance(config, dict) else None,
                    automatic_mode_switch=False, modes=dict(chatgpt_subscription=SUBSCRIPTION, api_billing=API))
    from trust import canonical
    if expected['selected'] not in MODES or canonical(config) != canonical(expected):
        raise ValueError('Unsupported or weakened execution/billing configuration')
    mode = expected['selected'] if selected is None else selected
    if mode not in MODES:
        raise ValueError('Unknown execution/billing mode; no fallback')
    return mode


def read_modes(root, selected=None):
    config = json.loads((Path(root)/'config/execution-modes.json').read_text())
    return config, validate_modes(config, selected)


class SubscriptionUsageMonitor:
    """Latching exhaustion/failure monitor; it never admits or retries a task.

    app-server camelCase fields match locally generated CLI 0.163.0 public schema.
    CLI JSONL failures have message-only details in the inspected source; prose
    cannot reliably distinguish entitlement exhaustion from other errors.
    """
    def __init__(self, thread, turn):
        if not isinstance(thread, str) or not thread or not isinstance(turn, str) or not turn:
            raise ValueError('Expected trusted thread and turn identities required')
        self.thread, self.turn, self.state = thread, turn, 'unknown'

    def observe(self, event, interface):
        if self.state in ('exhausted', 'failed_unknown'):
            return self.result()
        try:
            if not isinstance(event, dict): raise ValueError()
            if interface == 'cli_jsonl':
                if event.get('type') in ('error', 'turn.failed'):
                    self.state = 'failed_unknown'
            elif interface == 'app_server':
                method, params = event['method'], event['params']
                if method in ('error', 'turn/completed'):
                    if params['threadId'] != self.thread: raise ValueError()
                    if method == 'error':
                        if params['turnId'] != self.turn: raise ValueError()
                        error = params['error']
                        self.state = 'exhausted' if error.get('codexErrorInfo') == 'usageLimitExceeded' else 'failed_unknown'
                    else:
                        turn = params['turn']
                        if turn['id'] != self.turn: raise ValueError()
                        if turn['status'] != 'completed':
                            error = turn.get('error') or {}
                            self.state = 'exhausted' if error.get('codexErrorInfo') == 'usageLimitExceeded' else 'failed_unknown'
                elif method == 'account/rateLimits/updated':
                    snapshots = [params.get('rateLimits')]
                    buckets = params.get('rateLimitsByLimitId')
                    if buckets is not None:
                        if not isinstance(buckets, dict): raise ValueError()
                        snapshots.extend(buckets.values())
                    observed = False
                    for snapshot in snapshots:
                        if snapshot is None: continue
                        if not isinstance(snapshot, dict): raise ValueError()
                        reached, spend = snapshot.get('rateLimitReachedType'), snapshot.get('spendControlReached')
                        if reached not in (None, 'rate_limit_reached', 'workspace_owner_credits_depleted',
                                           'workspace_member_credits_depleted', 'workspace_owner_usage_limit_reached',
                                           'workspace_member_usage_limit_reached'):
                            raise ValueError()
                        if spend is not None and type(spend) is not bool: raise ValueError()
                        if reached is not None or spend is True:
                            self.state = 'exhausted'; break
                        for field in ('primary', 'secondary'):
                            window = snapshot.get(field)
                            if window is None: continue
                            used = window['usedPercent']
                            if type(used) not in (int, float) or not math.isfinite(used) or used < 0: raise ValueError()
                            observed = True
                            if used >= 100: self.state = 'exhausted'; break
                        if self.state == 'exhausted': break
                    if self.state != 'exhausted':
                        self.state = 'quota_observed' if observed else 'unknown'
                # Other official stream notifications do not establish quota.
            else:
                raise ValueError()
        except (KeyError, TypeError, ValueError, AttributeError):
            self.state = 'failed_unknown'
        return self.result()

    def result(self):
        return dict(state=self.state, stop=self.state != 'quota_observed',
                    automatic_retry=False, buy_credits=False, paid_refill=False,
                    fallback_mode=None, may_dispatch=False, guaranteed_per_task_cutoff=False)
