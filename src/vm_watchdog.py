"""Independent privileged host timer. Failure requires host-level fencing.

Provider inventory is authoritative and persists deadlines before provisioning.
An unavailable controller or unreadable ledger causes termination of all VMs.
No termination receipt is produced if provider inventory/removal is uncertain.
"""
import argparse
import json
from pathlib import Path
import socket
import time
from readiness import protected_file
from vm_runtime import UnixVMProvider


def tick(provider, now, controller_healthy):
    inventory = provider.call('inventory', {})
    if not isinstance(inventory, list):
        raise ValueError('Inventory unavailable; fence worker host externally')
    removed = []
    for item in inventory:
        execution = item['execution']
        import re
        if not re.fullmatch('[a-f0-9]{32}', execution):
            raise ValueError('Invalid inventory identity; fence host externally')
        issued, deadline = item.get('issued'), item.get('deadline')
        valid = (type(issued) is int and type(deadline) is int
                 and issued <= now < deadline <= issued+2400)
        if not valid or not controller_healthy:
            provider.call('terminate', dict(execution=execution))
            result = provider.call('absent', dict(execution=execution))
            if result != dict(execution=execution, vm_absent=True, disks_absent=True,
                              transport_revoked=True, watchdog_record_retained=True):
                raise RuntimeError('Host fence required: cleanup cannot be verified')
            removed.append(execution)
    return removed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, default=Path('/etc/fort-custer/controller.json'))
    args = parser.parse_args()
    config = json.loads(protected_file(args.config).read_text())
    healthy = False
    try:
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(3); client.connect(config['socket'])
            client.sendall(b'{"operation":"status"}\n'); client.shutdown(socket.SHUT_WR)
            response = json.loads(client.recv(8192))
            healthy = response.get('stopped') is False
    except (OSError, ValueError): pass
    print(json.dumps(dict(terminated=tick(UnixVMProvider(config['provider_socket']), int(time.time()), healthy))))


if __name__ == '__main__': main()
