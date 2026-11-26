"""Landlock for the brain (docs/sysop-brain-design.md 3.4): deny every filesystem write outside a few folders, reads stay open. Standard
library only (ctypes), Linux only; applied in the child between fork and exec, so the brain and everything it starts (its MCP proxy) are in
the domain, and the service is not.

What it does not cover: reads, the network, unix sockets (connecting to an existing socket is not a filesystem write; that is how the proxy
reaches the MCP server, which runs outside the domain). It is defence in depth, not the boundary: the boundary is the MCP server's policy.
"""
import ctypes
import os
import struct

SYS_CREATE_RULESET, SYS_ADD_RULE, SYS_RESTRICT_SELF = 444, 445, 446      # the same numbers on every architecture (generic syscall table)
CREATE_RULESET_VERSION = 1
RULE_PATH_BENEATH = 1
PR_SET_NO_NEW_PRIVS = 38

# write-like rights by ABI: WRITE_FILE, REMOVE_DIR, REMOVE_FILE, MAKE_CHAR, MAKE_DIR, MAKE_REG, MAKE_SOCK, MAKE_FIFO, MAKE_BLOCK, MAKE_SYM (ABI 1),
# REFER (ABI 2), TRUNCATE (ABI 3)
_WRITE_BITS = {1: (1, 4, 5, 6, 7, 8, 9, 10, 11, 12), 2: (13,), 3: (14,)}


def _libc():
    return ctypes.CDLL(None, use_errno=True)


def abi():
    """The Landlock ABI of the kernel, or 0 when there is none (no Landlock, a seccomp filter that refuses it, not Linux)."""
    try:
        r = _libc().syscall(SYS_CREATE_RULESET, None, 0, CREATE_RULESET_VERSION)
    except (OSError, AttributeError):
        return 0
    return r if r > 0 else 0


def write_rights(version):
    bits = 0
    for v in range(1, min(version, 3) + 1):
        for b in _WRITE_BITS[v]:
            bits |= 1 << b
    return bits


def restrict_writes(dirs):
    """Allow writes only under `dirs` for this process and its children, for good. Returns the ABI used (> 0), or 0 when Landlock is not
    available (nothing is changed then). Raises OSError when it is available but a step fails (a folder that does not exist)."""
    version = abi()
    if not version:
        return 0
    libc = _libc()
    rights = write_rights(version)
    attr = ctypes.create_string_buffer(struct.pack("Q", rights))
    fd = libc.syscall(SYS_CREATE_RULESET, attr, 8, 0)
    if fd < 0:
        e = ctypes.get_errno()
        raise OSError(e, "landlock_create_ruleset: %s" % os.strerror(e))
    try:
        for d in dirs:
            pfd = os.open(d, os.O_PATH | os.O_CLOEXEC)
            try:
                rule = ctypes.create_string_buffer(struct.pack("=Qi", rights, pfd))      # struct landlock_path_beneath_attr is packed
                if libc.syscall(SYS_ADD_RULE, fd, RULE_PATH_BENEATH, rule, 0) < 0:
                    e = ctypes.get_errno()
                    raise OSError(e, "landlock_add_rule %s: %s" % (d, os.strerror(e)))
            finally:
                os.close(pfd)
        if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) < 0:
            e = ctypes.get_errno()
            raise OSError(e, "prctl(NO_NEW_PRIVS): %s" % os.strerror(e))
        if libc.syscall(SYS_RESTRICT_SELF, fd, 0) < 0:
            e = ctypes.get_errno()
            raise OSError(e, "landlock_restrict_self: %s" % os.strerror(e))
    finally:
        os.close(fd)
    return version
