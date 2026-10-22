"""Pure App setup/token contracts. No keys generated, tokens requested or App installed."""
from datetime import datetime, timezone
import re
from trust import require_live

REPOSITORIES = frozenset(('MZKZxyz/fort-custer-automation','MZKZxyz/fort-custer-client','MZKZxyz/fort-custer-server'))
PERMISSIONS = {
    'reader':{'contents':'read','issues':'read'},
    'publisher':{'contents':'write','pull_requests':'write'},
}


def token_request(role, repository):
    if role not in PERMISSIONS or repository not in REPOSITORIES:
        raise ValueError('Authorized App role and repository required')
    return {'repositories':[repository.split('/')[1]],'permissions':dict(PERMISSIONS[role])}


def jwt_claims(client_id, now):
    if not isinstance(client_id,str) or not re.fullmatch(r'[A-Za-z0-9_.-]+',client_id) or type(now) is not int:
        raise ValueError('Configured App client ID and clock required')
    return dict(iss=client_id,iat=now-60,exp=now+540)


def validate_token_response(response, role, repository, now):
    """Called only inside the trusted broker, never serialize its return value."""
    requested=token_request(role,repository)
    try:
        expires=datetime.fromisoformat(response['expires_at'].replace('Z','+00:00')).timestamp()
        if (not now+30 < expires <= now+3600 or not isinstance(response['token'],str)
                or not response['token'] or {k:v for k,v in response['permissions'].items() if k!='metadata'} != requested['permissions']
                or response['permissions'].get('metadata','read') != 'read'
                or [r['full_name'] for r in response['repositories']] != [repository]):
            raise ValueError()
    except (KeyError,TypeError,ValueError,OverflowError):
        raise ValueError('Token scope or lifetime unverifiable') from None
    return response['token']


class InstallationTokenBroker:
    def mint(self, *args, **kwargs):
        # Live integration requires separately deployed KMS signer, authenticated
        # operator grant and audited broker; a username/header is insufficient.
        require_live()
