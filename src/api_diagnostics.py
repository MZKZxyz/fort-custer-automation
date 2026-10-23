"""Fixed diagnostic vocabulary. Never serialize exception/provider strings."""
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


def diagnostic(category, phase='helper', dispatch='may_have_been_sent', http_status=None, parameter=None):
    # Reconstruct all values from finite vocabularies; no arbitrary fields survive IPC.
    return dict(category=category if category in CATEGORIES else 'controller_error',
        phase=phase if phase in PHASES else 'controller',
        dispatch=dispatch if dispatch in DISPATCH else 'may_have_been_sent',
        http_status=http_status if type(http_status) is int and 100 <= http_status <= 599 else None,
        parameter=parameter if parameter in PARAMETERS else None)


def validate(value):
    if not isinstance(value, dict) or set(value) != {'category','phase','dispatch','http_status','parameter'}:
        raise ValueError('Invalid diagnostic envelope')
    clean = diagnostic(**value)
    if clean != value: raise ValueError('Invalid diagnostic vocabulary')
    return clean


class APIUnavailable(ValueError):
    def __init__(self, category, phase='helper', dispatch='may_have_been_sent', http_status=None, parameter=None):
        self.diagnostic = diagnostic(category, phase, dispatch, http_status, parameter)
        self.request_id = None
        self.audit_recorded = False
        super().__init__(self.diagnostic['category'])
