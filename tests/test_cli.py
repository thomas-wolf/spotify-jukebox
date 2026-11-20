

def test_runtime_dir_points_at_our_own_user_not_root():
    from jukebox.cli import fix_runtime_dir
    env = {"XDG_RUNTIME_DIR": "/run/user/0"}       # what %U in a system unit used to give
    fix_runtime_dir(env, uid=998)
    assert env["XDG_RUNTIME_DIR"] == "/run/user/998"
    env = {}
    fix_runtime_dir(env, uid=998)
    assert env["XDG_RUNTIME_DIR"] == "/run/user/998"
    env = {"XDG_RUNTIME_DIR": "/somewhere/else"}   # a deliberate value stays
    fix_runtime_dir(env, uid=998)
    assert env["XDG_RUNTIME_DIR"] == "/somewhere/else"
    env = {}
    fix_runtime_dir(env, uid=0)                    # root is left alone
    assert env == {}
