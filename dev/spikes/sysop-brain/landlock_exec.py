"""landlock_exec.py DIR[:DIR...] -- CMD...: deny every filesystem write outside the DIRs (reads stay open), then exec CMD. Landlock ABI >= 3."""
import ctypes, os, struct, sys
libc = ctypes.CDLL(None, use_errno=True)
SYS_CREATE, SYS_ADD, SYS_RESTRICT = 444, 445, 446
W = 0
for bit in (1, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14):   # WRITE_FILE, REMOVE_DIR/FILE, MAKE_*, REFER, TRUNCATE
    W |= 1 << bit
dirs, cmd = sys.argv[1].split(":"), sys.argv[sys.argv.index("--") + 1:]
attr = ctypes.create_string_buffer(struct.pack("Q", W))
fd = libc.syscall(SYS_CREATE, attr, 8, 0)
if fd < 0:
    sys.exit("landlock unavailable: %s" % os.strerror(ctypes.get_errno()))
for d in dirs:
    pfd = os.open(d, os.O_PATH | os.O_CLOEXEC)
    rule = ctypes.create_string_buffer(struct.pack("=Qi", W, pfd))   # packed landlock_path_beneath_attr
    if libc.syscall(SYS_ADD, fd, 1, rule, 0) < 0:
        sys.exit("add_rule %s: %s" % (d, os.strerror(ctypes.get_errno())))
    os.close(pfd)
if libc.prctl(38, 1, 0, 0, 0) < 0 or libc.syscall(SYS_RESTRICT, fd, 0) < 0:   # PR_SET_NO_NEW_PRIVS, restrict_self
    sys.exit("restrict: %s" % os.strerror(ctypes.get_errno()))
os.execvp(cmd[0], cmd)
