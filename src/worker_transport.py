"""One-shot bounded AF_UNIX transport. Identity authentication is not a sandbox.

No process launcher, network listener, credentials, environment or descriptor
transfer. The controller connects to an administrator-provisioned endpoint.
"""
import ctypes
import os
from pathlib import Path
import socket
import stat
import struct
import sys
import time

from src import orchestration_evidence as e

MAXIMUM = 1024 * 1024


def peer_uid(sock):
    if sys.platform.startswith('linux') and hasattr(socket, 'SO_PEERCRED'):
        return struct.unpack('3i', sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]
    if sys.platform == 'darwin':
        # Python does not expose getpeereid on all macOS builds. Use libc's
        # documented uid_t/gid_t API on a connected local stream socket.
        libc = ctypes.CDLL(None, use_errno=True)
        uid, gid = ctypes.c_uint(), ctypes.c_uint()
        fn = libc.getpeereid
        fn.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)]
        fn.restype = ctypes.c_int
        e.require(fn(sock.fileno(), ctypes.byref(uid), ctypes.byref(gid)) == 0,
                  'Peer credentials unavailable')
        return uid.value
    raise ValueError('Unsupported peer credential platform')


def _timeout(sock, deadline):
    left = deadline-time.monotonic()
    e.require(left > 0, 'Transport deadline')
    sock.settimeout(left)


def _read(sock, size, deadline):
    out = bytearray()
    while len(out) < size:
        _timeout(sock, deadline)
        # recvmsg rejects SCM_RIGHTS instead of accidentally accepting open
        # controller/worker file descriptors as artifact capabilities.
        chunk, ancillary, flags, _ = sock.recvmsg(min(size-len(out), 65536), socket.CMSG_SPACE(4*16))
        for level, kind, data in ancillary:
            if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                import array
                fds = array.array('i')
                fds.frombytes(data[:len(data)-(len(data) % fds.itemsize)])
                for fd in fds: os.close(fd)
        e.require(not ancillary and not flags & (socket.MSG_CTRUNC | socket.MSG_TRUNC),
                  'Descriptor or truncated message rejected')
        e.require(bool(chunk), 'Truncated transport frame')
        out.extend(chunk)
    return bytes(out)


def receive(sock, deadline):
    size = struct.unpack('!I', _read(sock, 4, deadline))[0]
    e.require(0 < size <= MAXIMUM, 'Transport response size')
    return _read(sock, size, deadline)


def send(sock, raw, deadline):
    e.require(type(raw) is bytes and 0 < len(raw) <= MAXIMUM, 'Transport request size')
    frame = struct.pack('!I', len(raw))+raw
    while frame:
        _timeout(sock, deadline)
        count = sock.send(frame)
        e.require(count > 0, 'Disconnected transport')
        frame = frame[count:]


def finish_request(sock):
    # Darwin can report ENOTCONN here when a malformed/early-closing peer
    # disconnects immediately after send. Do not continue to accept any reply
    # or retry; expose the same protocol rejection as a truncated frame.
    try:
        sock.shutdown(socket.SHUT_WR)
    except OSError:
        raise ValueError('Disconnected transport before response') from None


def exchange(path, request, expected_uid, seconds):
    """Authenticate kernel peer before sending bytes; never reconnect or retry.

    Same-UID endpoints are allowed for synthetic fixtures only by their caller.
    Use IsolatedEndpoint for the distinct-principal boundary. Neither API grants
    execution or certifies filesystem/network isolation.
    """
    e.require(type(expected_uid) is int and expected_uid > 0 and e.finite(seconds) and
              0 < seconds <= 2400, 'Explicit unprivileged peer and deadline required')
    e.require(type(request) is bytes and 0 < len(request) <= MAXIMUM, 'Transport request size')
    path = Path(path)
    e.require(path.is_absolute(), 'Absolute endpoint required')
    for parent in path.parents:
        s = parent.lstat()
        e.require(stat.S_ISDIR(s.st_mode) and not stat.S_ISLNK(s.st_mode) and
                  (not s.st_mode & 0o022 or parent != path.parent and s.st_mode & stat.S_ISVTX),
                  'Untrusted endpoint directory')
        e.require(s.st_uid in (0, os.getuid(), expected_uid), 'Untrusted endpoint owner')
    s = path.lstat()
    e.require(stat.S_ISSOCK(s.st_mode) and s.st_uid == expected_uid and not s.st_mode & 0o007,
              'Unsafe endpoint type, owner or permissions')
    end = time.monotonic()+seconds
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.set_inheritable(False)
        _timeout(sock, end)
        sock.connect(str(path))
        e.require(peer_uid(sock) == expected_uid, 'Wrong worker peer identity')
        send(sock, request, end)
        finish_request(sock)
        response = receive(sock, end)
        # A one-shot response must close. Reject trailing frames/replays and
        # bound a peer which sends its frame but never completes the stream.
        _timeout(sock, end)
        extra, ancillary, flags, _ = sock.recvmsg(1, socket.CMSG_SPACE(64))
        if ancillary:
            for level, kind, data in ancillary:
                if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                    import array
                    fds = array.array('i'); fds.frombytes(data[:len(data)-len(data)%4])
                    for fd in fds: os.close(fd)
        e.require(not extra and not ancillary and not flags, 'Trailing response or descriptors')
        return response


class IsolatedEndpoint:
    def __init__(self, path, uid):
        e.require(type(uid) is int and uid > 0 and uid != os.getuid(),
                  'Distinct unprivileged security principal required')
        self.path, self.uid = path, uid

    def exchange(self, request, seconds):
        return exchange(self.path, request, self.uid, seconds)
