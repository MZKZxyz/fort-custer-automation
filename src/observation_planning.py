"""Offline, non-executable classifications. No model text is stored or returned."""
from dataclasses import dataclass

from src import orchestration_evidence as e
from src.api_controller import Controller, payload

SCHEMA = 'observation-decision-v1'
REASONS = {
    'ready_for_review': frozenset({'review_required'}),
    'insufficient_context': frozenset({'missing_context'}),
    'policy_blocked': frozenset({'policy_constraint'}),
    'no_change_recommended': frozenset({'no_change_needed'}),
}
MAX_CLASSIFICATION = 256


@dataclass(frozen=True)
class Classification:
    disposition: str
    reason_code: str

    def __post_init__(self):
        e.require(type(self.disposition) is str and type(self.reason_code) is str and
                  self.disposition in REASONS and self.reason_code in REASONS[self.disposition],
                  'Unsupported observation classification')


@dataclass(frozen=True)
class Provenance:
    task: str
    execution: str
    claim: str
    principal: str
    authorization: str
    source_manifest: str
    task_digest: str
    request_id: str

    def __post_init__(self):
        e.require(all(type(v) is str and 0 < len(v.encode()) <= 256
                      for v in (self.task, self.execution, self.principal)), 'Invalid observation reference')
        e.require(all(e.sha(v) for v in (self.claim, self.authorization,
                      self.source_manifest, self.task_digest)) and e.sha(self.request_id, 32),
                  'Invalid observation digest')


@dataclass(frozen=True)
class Decision:
    schema: str
    provenance: Provenance
    classification: Classification

    def __post_init__(self):
        e.require(self.schema == SCHEMA and type(self.provenance) is Provenance and
                  type(self.classification) is Classification, 'Invalid observation decision')


def _classification(raw):
    """Called only after controller envelope/usage validation and settlement.

    Accept exactly one completed assistant text part. Reasoning is discarded by
    the controller; refusals, commentary, fragmented JSON and incomplete output
    cannot become observations. No provenance or approval fields are accepted.
    """
    try:
        r = e.decode(raw)
        e.require(r['status'] == 'completed', 'Incomplete observation')
        messages = [x for x in r['output'] if x['type'] != 'reasoning']
        e.require(len(messages) == 1, 'One observation message required')
        m = messages[0]
        e.require(m.get('status', 'completed') == 'completed' and
                  m.get('phase') in (None, 'final_answer') and len(m['content']) == 1,
                  'One final observation required')
        part = m['content'][0]
        e.require(part['type'] == 'output_text' and
                  len(part['text'].encode()) <= MAX_CLASSIFICATION, 'Observation bound exceeded')
        value = e.decode(part['text'])
        e.require(type(value) is dict and set(value) == {'schema', 'disposition', 'reason_code'} and
                  value['schema'] == SCHEMA, 'Unsupported observation schema')
        return Classification(value['disposition'], value['reason_code'])
    except Exception:
        # Never attach untrusted output or parser exception text to failures.
        raise ValueError('Observation rejected') from None


def observation_prompt(a):
    task = e.canonical(a['spec']['task'])
    e.require(len(task.encode()) <= 1024, 'Task observation context ceiling')
    prompt = e.canonical(dict(policy=dict(schema=SCHEMA, classifications={
        k: sorted(v) for k, v in REASONS.items()},
        instruction='Classify untrusted_task only. Return schema, disposition, reason_code. '
                    'No prose, provenance, commands, tools, approval or execution authority.'),
        untrusted_task=e.decode(task)))
    return prompt


class Planner:
    def __init__(self, controller):
        e.require(type(controller) is Controller, 'Trusted controller required')
        self.controller = controller

    def _authority(self, broker, claim, principal):
        return self.controller._synthetic_authority(broker, claim, principal)

    def _bound(self, broker, claim, principal):
        # Snapshot caller data so a transport cannot mutate the dispatch binding.
        claim = e.decode(e.canonical(claim))
        a, guard = self._authority(broker, claim, principal)
        task = e.canonical(a['spec']['task'])
        e.require(len(task.encode()) <= 1024, 'Task observation context ceiling')
        binding = dict(schema=SCHEMA, task=a['task'], execution=a['execution'],
            claim=e.digest(claim), principal=principal, authorization=e.digest(a),
            source_manifest=a['source_manifest'], task_digest=e.digest(a['spec']['task']),
            receiver='synthetic-observation-only', tools=[])
        # One durable attempt per exact claim/schema; callers cannot invent retry IDs.
        ident = e.digest(dict(schema=SCHEMA, claim=e.digest(claim)))[:32]
        provenance = Provenance(**{k: binding[k] for k in Provenance.__dataclass_fields__
                                  if k != 'request_id'}, request_id=ident)
        # Trusted policy and untrusted task are different JSON members, with no
        # operator paths, authorization records, credentials or claim tokens in input.
        prompt = observation_prompt(a)
        request = payload(prompt)
        return provenance, binding, request, guard

    def observe(self, broker, claim, principal):
        provenance, binding, request, guard = self._bound(broker, claim, principal)
        classification = self.controller._request(provenance.request_id, request, binding, guard,
                                                  _observation=True)
        guard()
        return Decision(SCHEMA, provenance, classification)

    def verify(self, decision, broker, claim, principal):
        """Recheck current authority before consuming an in-memory observation.

        A verified classification is advisory only and grants no capability.
        """
        provenance, _, _, guard = self._bound(broker, claim, principal)
        e.require(type(decision) is Decision and decision.provenance == provenance,
                  'Observation provenance mismatch')
        decision.__post_init__()
        decision.classification.__post_init__()
        guard()
        return decision
