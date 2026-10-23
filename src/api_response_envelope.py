"""Reviewed receipt/security projection, not a complete provider envelope schema.

OpenAPI 2.3.0, commit 0938b0f003300cd4c6ec39191532df81b04dfae1;
openai-python d622f28ad5cb3f947541936c0c139891211a42c5. See
 docs/RESPONSES-ENVELOPE-SCHEMA.md for the complete inventory and policies.
"""
SDK_FIELDS = frozenset({
    'id','object','created_at','status','error','incomplete_details','instructions',
    'max_output_tokens','model','output','parallel_tool_calls','previous_response_id',
    'reasoning','temperature','text','tool_choice','tools','top_p','truncation',
    'usage','user','metadata','service_tier','background','max_tool_calls','safety_identifier',
    'prompt_cache_key','prompt_cache_retention','top_logprobs','completed_at','conversation',
    'prompt','prompt_cache_diagnostics','prompt_cache_options','access_programs','moderation'})
# OpenAPI describes this SDK convenience property as nullable text. It is never
# authority, a fallback for output, a usage source, or persisted model output.
DISCARDED_TEXT_FIELDS = frozenset({'output_text'})
OPENAPI_FIELDS = SDK_FIELDS | DISCARDED_TEXT_FIELDS
# store is present in the official example and CreateResponse, but not the
# Response properties / generated SDK serialized fields. Keep its strict false check.
# Operator-observed penalty echoes are validated as finite numbers and discarded.
# Operator-observed tool_usage is accepted only with reviewed zero counters.
REVIEWED_FIELDS = OPENAPI_FIELDS | {'store','frequency_penalty','presence_penalty','tool_usage'}
# Known request-only configuration remains forbidden in a response even when
# null or empty. Other unfamiliar top-level metadata is outside the projection.
REQUEST_ONLY_FIELDS = frozenset({'context_management','include','input','stream','stream_options'})
# Retained only to decode historical diagnostics, never to label new metadata.
DIAGNOSTIC_FIELDS = REVIEWED_FIELDS | REQUEST_ONLY_FIELDS

