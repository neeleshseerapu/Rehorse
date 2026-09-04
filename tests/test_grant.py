"""grant.py: one-shot merge/discard authorization files under ~/.rehorse/, minted only by the UserPromptSubmit hook."""
import json
import os
import time

import grant


def test_mint_writes_a_private_file_outside_the_repo(home):
    p = grant.mint("merge", "t-1", "sess")
    assert p == str(home / ".rehorse" / "merge-t-1")
    assert oct(os.stat(p).st_mode & 0o777) == "0o600"
    assert json.load(open(p)) == {"action": "merge", "task": "t-1", "session_id": "sess"}


def test_present_and_take_are_one_shot(home):
    assert not grant.present("t-1")
    grant.mint("discard", "t-1", "sess")
    assert grant.present("t-1")
    assert not grant.take("merge", "t-1")  # wrong action does not consume
    assert grant.take("discard", "t-1")
    assert not grant.take("discard", "t-1")  # consumed
    assert not grant.present("t-1")


def test_stale_tokens_are_ignored(home):
    p = grant.mint("merge", "t-1", "sess")
    old = time.time() - grant.TTL - 1
    os.utime(p, (old, old))
    assert not grant.present("t-1")
    assert not grant.take("merge", "t-1")


def test_clear_drops_every_token_for_the_given_tasks(home):
    grant.mint("merge", "t-1", "s")
    grant.mint("discard", "t-2", "s")
    grant.mint("merge", "t-other", "s")
    grant.clear(["t-1", "t-2"])
    assert not grant.present("t-1") and not grant.present("t-2") and grant.present("t-other")
