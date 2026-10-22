"""Fixed negative probes; no commands or destinations come from issue text."""
import os
import ctypes
from pathlib import Path
import resource
import socket

def probe():
    checks = {'nondumpable_supervisor':ctypes.CDLL(None,use_errno=True).prctl(3,0,0,0,0) == 0, 'nonroot':os.getuid() not in (0,), 'no_controller':not Path('/opt/controller').exists(),
              'no_socket':not Path('/var/run/docker.sock').exists(),
              'no_ledger':not Path('/state').exists(),
              'no_capabilities':'CapEff:\t0000000000000000' in Path('/proc/self/status').read_text(),
              'no_new_privileges':ctypes.CDLL(None,use_errno=True).prctl(39,0,0,0,0) == 1,
              'file_limit':resource.getrlimit(resource.RLIMIT_FSIZE)[1] == 8388608}
    for path in ('/etc/fc-escape','/opt/fc-escape'):
        try:
            Path(path).write_text('escape')
            checks['readonly:'+path] = False
        except OSError:
            checks['readonly:'+path] = True
    for address in ('169.254.169.254','10.0.0.1','192.168.1.1','1.1.1.1'):
        try:
            with socket.create_connection((address,80),timeout=.3):
                checks['network:'+address] = False
        except OSError:
            checks['network:'+address] = True
    for path,limit in (('/workspace',256*1024*1024),('/tmp',64*1024*1024)):
        stat=os.statvfs(path)
        checks['disk:'+path]=0 < stat.f_blocks*stat.f_frsize <= limit
    for key in os.environ:
        if any(word in key.upper() for word in ('TOKEN','SECRET','PASSWORD','API_KEY')):
            checks['no_credentials'] = False
    checks.setdefault('no_credentials',True)
    if not all(checks.values()):
        raise RuntimeError('Sandbox negative probe failed: '+repr(checks))
    return checks
