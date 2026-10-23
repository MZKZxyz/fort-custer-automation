"""Codex boundary preparation and sanitized usage classification; live blocked.

No credential forwarding, account-file copying, subprocess or retry is possible
here. Existing account authentication has not demonstrated tool/credential
separation. The required replacement is described in WORKER-ISOLATION.md.
"""
from src import orchestration_evidence as e

CLI_VERSION = '0.163.0'
TOKENS = ('input_tokens', 'cached_input_tokens', 'output_tokens')


def authentication_boundary():
    return dict(schema='codex-auth-boundary-v1', cli_version=CLI_VERSION,
                state='blocked', account_files_forwarded=False,
                reason='personal-account-auth-not-proven-inaccessible-to-generated-code',
                required='supported credential-isolating model/tool relay or separately reviewed dedicated identity',
                api_fallback=False, paid_refills=False)


def usage_outcome(raw):
    """Normalize pinned CLI JSONL; retain no agent text or error messages.

    Only structured usageLimitExceeded is exhaustion evidence. Unknown/auth/
    protocol failures remain unknown; never guess quota from diagnostic strings.
    """
    e.require(type(raw) is bytes and 0 < len(raw) <= 1024*1024, 'CLI telemetry ceiling')
    try:
        events = [e.decode(line) for line in raw.splitlines()]
        e.require(all(isinstance(event, dict) for event in events), 'Invalid CLI telemetry')
    except (ValueError, TypeError, UnicodeError):
        return dict(state='unknown', usage=None, retry=False)
    failures = [event for event in events if event.get('type') in ('turn.failed', 'error')]
    if failures:
        exhausted = any(isinstance(event.get('error'), dict) and
                        event['error'].get('codexErrorInfo') == 'usageLimitExceeded' for event in failures)
        return dict(state='subscription-exhausted' if exhausted else 'unknown', usage=None, retry=False)
    kinds = [event.get('type') for event in events]
    known = {'thread.started', 'turn.started', 'item.started', 'item.updated',
             'item.completed', 'turn.completed'}
    if (len(kinds) < 3 or kinds[:2] != ['thread.started', 'turn.started'] or
        kinds[-1] != 'turn.completed' or kinds.count('thread.started') != 1 or
        kinds.count('turn.started') != 1 or kinds.count('turn.completed') != 1 or
        any(kind not in known for kind in kinds)):
        return dict(state='unknown', usage=None, retry=False)
    usage = events[-1].get('usage')
    if (not isinstance(usage, dict) or set(usage) != set(TOKENS) or
        any(type(usage[k]) is not int or usage[k] < 0 for k in TOKENS) or
        usage['cached_input_tokens'] > usage['input_tokens']):
        return dict(state='unknown', usage=None, retry=False)
    return dict(state='complete', usage={k:usage[k] for k in TOKENS}, retry=False)


class CodexWorker:
    """Real task entrypoint is deliberately unavailable, including with receipts."""
    def run(self, *args, **kwargs):
        from src.integration_control import block_live_dispatch
        block_live_dispatch()
        raise ValueError('Codex authentication boundary unsupported')
