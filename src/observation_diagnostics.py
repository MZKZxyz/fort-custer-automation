"""Finite observation failure vocabulary. No exception or provider data accepted."""
from src import orchestration_evidence as e

PHASES = {
    'provider_transport': 'provider_transport_or_validation_failure',
    'response_validation': 'provider_transport_or_validation_failure',
    'post_settlement_authorization': 'authorization_revalidation_failure',
    'classification': 'classification_failure',
    'final_verification': 'decision_verification_failure',
    'internal': 'unexpected_internal_failure',
    'settlement': 'unexpected_internal_failure',
}


def diagnostic(phase):
    e.require(type(phase) is str and phase in PHASES, 'Invalid observation diagnostic phase')
    return dict(category=PHASES[phase], phase=phase)


def validate(value):
    e.require(type(value) is dict and set(value) == {'category', 'phase'} and
              value == diagnostic(value['phase']), 'Invalid observation diagnostic')
    return dict(value)
