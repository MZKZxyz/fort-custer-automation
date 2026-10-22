"""Dedicated trusted host service. Never run inside worker/controller containers.

Observes Docker's own StartedAt, not a renewable worker heartbeat. Every labelled
container is killed after its original 2400s, even if the controller has died.
"""
from datetime import datetime, timezone
import json
import time
from infrastructure import docker


def expired(container, now):
    started=container['State']['StartedAt']
    if started.startswith('0001-'):
        # Never-started orphan containers are cleaned after creation deadline.
        started=container['Created']
    stamp=datetime.fromisoformat(started.replace('Z','+00:00')).timestamp()
    # Future/unparseable clocks are not trusted. Caller kills on parse errors.
    return stamp > now+5 or now-stamp >= 2400


def tick(now=None):
    now=time.time() if now is None else now
    ids=docker('ps','-aq','--filter','label=fc.sprint=5.4').stdout.decode().split()
    for container_id in ids:
        data=json.loads(docker('inspect',container_id).stdout)[0]
        try: stop=expired(data,now)
        except (KeyError,TypeError,ValueError): stop=True
        if stop:
            docker('rm','--force',container_id,timeout=15)
            print(json.dumps(dict(event='deadline_removed',container=container_id)),flush=True)
    return len(ids)


def main():
    while True:
        try: tick()
        except Exception:
            # Service failure must page operator; do not attest clean inventory.
            print('{"event":"watchdog_failure","action":"stop_dispatch_investigate"}',flush=True)
            raise
        time.sleep(1)

if __name__=='__main__': main()
