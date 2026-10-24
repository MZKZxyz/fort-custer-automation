"""Finite stage diagnostics; never consume arbitrary exception strings."""
from src import orchestration_evidence as e

PHASES = {'internal', 'provider_transport', 'response_validation', 'settlement',
          'post_settlement_authorization', 'coding_response', 'edit_validation',
          'independent_qa', 'final_verification'}


def diagnostic(phase):
    e.require(phase in PHASES, 'Unknown coding stage')
    return dict(category='coding_canary_failure', phase=phase, retry=False)


def validate(value):
    e.require(isinstance(value, dict) and value == diagnostic(value['phase']),
              'Invalid coding diagnostic')
    return dict(value)
