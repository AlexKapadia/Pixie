"""Cross-platform smoke tests (Phase 6f).

These tests parametrise OS-divergent code paths over ``sys.platform`` /
``os.name`` so we can prove POSIX and Windows branches without
actually being on both machines. Subprocess and OS-specific calls are
mocked throughout -- we never invoke the real signal/fork/Popen
machinery here.
"""
