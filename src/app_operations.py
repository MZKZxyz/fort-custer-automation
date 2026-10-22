"""Reviewed GitHub App lifecycle contract, exercised against synthetic transport.

Transport must use a separately provisioned KMS-backed App signer. No private key
generation and no live token mint are available during Sprint 5.5.
"""
from github_app_setup import token_request, validate_token_response
from trust import require_live


def verify_installation(response, app_id, installation_id, owner):
    if (type(app_id) is not int or type(installation_id) is not int
            or response.get('id') != installation_id or response.get('app_id') != app_id
            or response.get('account', {}).get('login') != owner
            or response.get('repository_selection') != 'selected' or response.get('suspended_at') is not None):
        raise ValueError('App installation identity, selection or suspension rejected')


class AppOperations:
    def __init__(self, transport, verifier, clock, identities, ledger=None):
        if set(identities) != {'reader', 'publisher'} or identities['reader']['app_id'] == identities['publisher']['app_id']:
            raise ValueError('Separate reader and publisher App identities required')
        self.transport, self.verifier, self.clock, self.identities = transport, verifier, clock, identities
        if ledger is None:
            raise ValueError('Authoritative approval nonce and audit ledger required')
        self.ledger = ledger
        self.tokens = {}

    def event(self, event, payload):
        with self.ledger.tx() as db:
            self.ledger.event(db, payload['execution'], event, payload)

    def mint(self, role, repository, execution, grant):
        if not self.transport.synthetic: require_live()
        request = token_request(role, repository)
        binding = dict(role=role, repository=repository, execution=execution)
        identity = self.identities[role]
        installation = self.transport.installation(identity['installation_id'])
        verify_installation(installation, identity['app_id'], identity['installation_id'], repository.split('/')[0])
        if self.transport.repositories(identity['installation_id']) != [repository]:
            raise ValueError('Installation must be restricted to exactly the target repository')
        with self.ledger.tx() as db:
            prior = db.execute("SELECT payload FROM s53_events WHERE run=? AND event='token_mint_requested'", (execution,)).fetchall()
            import json
            if any(json.loads(row[0])['role'] == role for row in prior):
                raise ValueError('Token mint already requested; authoritative reconciliation required')
            self.verifier.consume(db, grant, 'app-token', binding, self.clock())
            self.ledger.event(db, execution, 'token_mint_requested', binding)
        response = self.transport.mint(identity['installation_id'], request)
        token = validate_token_response(response, role, repository, self.clock())
        self.tokens[(role, execution)] = dict(response=response, repository=repository)
        self.event('token_minted', dict(role=role, execution=execution, repository=repository, expires=response['expires_at']))
        return token

    def get(self, role, execution):
        item = self.tokens[(role, execution)]
        return validate_token_response(item['response'], role, item['repository'], self.clock())

    def revoke(self, role, execution):
        item = self.tokens.pop((role, execution), None)
        if item:
            # DELETE /installation/token, performed by the trusted transport.
            # On ambiguity the local authority stays revoked; provider revocation
            # remains unresolved and activation must fail until verified.
            self.transport.revoke(item['response']['token'])
            self.event('token_revoked', dict(role=role, execution=execution))
