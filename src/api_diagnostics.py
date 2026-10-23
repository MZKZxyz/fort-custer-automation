"""Fixed diagnostic vocabulary. Never serialize exception/provider strings."""
from src.api_response_envelope import DIAGNOSTIC_FIELDS

CATEGORIES = frozenset({'credential_unreadable', 'credential_format', 'local_request_invalid',
    'helper_start_failed', 'helper_disconnected', 'helper_deadline', 'helper_protocol_invalid',
    'connect_failed', 'connect_timeout', 'tls_verification_failed', 'transport_failure',
    'transport_timeout', 'request_rejected', 'unsupported_parameter', 'authentication',
    'permission_denied', 'rate_limit_or_exhaustion', 'model_or_endpoint_not_found',
    'provider_error', 'redirect_rejected', 'http_error', 'response_too_large',
    'credential_echo', 'response_schema_invalid', 'response_json_invalid',
    'controller_error', 'local_configuration_or_budget'})
PHASES = frozenset({'credential', 'local_request', 'helper_start', 'helper', 'connect',
                   'request', 'response_headers', 'response_body', 'response_validation', 'controller'})
DISPATCH = frozenset({'not_attempted', 'may_have_been_sent', 'response_received'})
PARAMETERS = frozenset({'model','input','max_output_tokens','store','background','stream',
    'tools','tool_choice','parallel_tool_calls','truncation','service_tier','reasoning',
    'reasoning.effort','prompt_cache_retention'})


VALIDATION_RULES = {
    'envelope': {'size','shape','unknown_fields','object','model','json'},
    'metadata': {'field_type','unsupported_configuration','service_tier','cache_policy'},
    'completion': {'response_status','provider_error','incomplete_details'},
    'usage': {'shape','unknown_dimension','token_type','token_bounds','total_mismatch'},
    'cached_tokens': {'shape','unknown_dimension','token_type','token_bounds','cache_write_not_priced'},
    'reasoning_tokens': {'shape','unknown_dimension','token_type','token_bounds'},
    'output': {'shape','item_type','unknown_fields','item_status'},
    'message': {'shape','unknown_fields','role','phase'},
    'content': {'shape','unknown_fields','text_type','annotations','logprobs'},
    'reasoning': {'shape','unknown_fields','summary','content','encrypted_content'},
    'internal': {'unexpected_validation_error'},
}


def diagnostic(category, phase='helper', dispatch='may_have_been_sent', http_status=None, parameter=None,
               validation_section=None, validation_rule=None,
               unrecognized_fields=None, other_unrecognized_fields=None):
    # Reconstruct all values from finite vocabularies; no arbitrary fields survive IPC.
    result = dict(category=category if category in CATEGORIES else 'controller_error',
        phase=phase if phase in PHASES else 'controller',
        dispatch=dispatch if dispatch in DISPATCH else 'may_have_been_sent',
        http_status=http_status if type(http_status) is int and 100 <= http_status <= 599 else None,
        parameter=parameter if parameter in PARAMETERS else None)

    if validation_section is not None or validation_rule is not None:
        if (isinstance(validation_section, str) and isinstance(validation_rule, str) and
                validation_rule in VALIDATION_RULES.get(validation_section, set())):
            result.update(validation_section=validation_section, validation_rule=validation_rule)
        else:
            result.update(validation_section='internal', validation_rule='unexpected_validation_error')
    if unrecognized_fields is not None or other_unrecognized_fields is not None:
        if (result['category'] == 'response_schema_invalid' and
                result.get('validation_section') == 'envelope' and
                result.get('validation_rule') == 'unknown_fields'):
            # Select from our fixed names, never serialize provider-controlled keys.
            names = unrecognized_fields if isinstance(unrecognized_fields, list) else []
            result['unrecognized_fields'] = sorted({name for name in names
                if isinstance(name, str) and name in DIAGNOSTIC_FIELDS})
            result['other_unrecognized_fields'] = other_unrecognized_fields is True
    return result


def validate(value):
    base = {'category','phase','dispatch','http_status','parameter'}
    validation = base | {'validation_section','validation_rule'}
    named = validation | {'unrecognized_fields','other_unrecognized_fields'}
    if not isinstance(value, dict) or set(value) not in (base, validation, named):
        raise ValueError('Invalid diagnostic envelope')
    if set(value) == named:
        if (not isinstance(value['unrecognized_fields'], list) or
                type(value['other_unrecognized_fields']) is not bool or
                not (value['unrecognized_fields'] or value['other_unrecognized_fields'])):
            raise ValueError('Invalid diagnostic envelope')
    clean = diagnostic(**value)
    if clean != value: raise ValueError('Invalid diagnostic vocabulary')
    return clean


class APIUnavailable(ValueError):
    def __init__(self, category, phase='helper', dispatch='may_have_been_sent', http_status=None, parameter=None,
                 validation_section=None, validation_rule=None,
                 unrecognized_fields=None, other_unrecognized_fields=None):
        self.diagnostic = diagnostic(category, phase, dispatch, http_status, parameter, validation_section, validation_rule,
                                     unrecognized_fields, other_unrecognized_fields)
        self.request_id = None
        self.audit_recorded = False
        super().__init__(self.diagnostic['category'])
