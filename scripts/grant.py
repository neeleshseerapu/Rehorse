#!/usr/bin/env python3
"""One-shot merge/discard grants: ~/.rehorse/<action>-<task-id>, outside every repo.

Minted only by authorize.py (the UserPromptSubmit hook, which fires for user-typed prompts alone), checked for
existence by guard_bash.py, consumed by merge.py / discard.py. A grant dies when consumed, on the next user prompt
(authorize.py clears), or after TTL seconds. The model never needs to read one, and guard_bash denies every
command that names this directory.
"""
import json
import os
import time

TTL = 3600
ACTIONS = ("merge", "discard")


def dir_():
    return os.path.join(os.path.expanduser("~"), ".rehorse")


def path(action, tid):
    return os.path.join(dir_(), "%s-%s" % (action, tid))


def fresh(p):
    try:
        return time.time() - os.stat(p).st_mtime < TTL
    except OSError:
        return False


def mint(action, tid, session_id):
    os.makedirs(dir_(), mode=0o700, exist_ok=True)
    p = path(action, tid)
    with os.fdopen(os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        json.dump({"action": action, "task": tid, "session_id": session_id}, f)
    os.chmod(p, 0o600)
    return p


def present(tid):
    """guard_bash: does the user hold a fresh grant of either kind for this task?"""
    return any(fresh(path(a, tid)) for a in ACTIONS)


def take(action, tid):
    """merge.py / discard.py: consume the grant. True only once, and only while fresh."""
    p = path(action, tid)
    ok = fresh(p)
    try:
        os.remove(p)
    except OSError:
        pass
    return ok


def clear(tids):
    for tid in tids:
        for a in ACTIONS:
            take(a, tid)
