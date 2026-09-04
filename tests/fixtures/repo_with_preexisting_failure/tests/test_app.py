from app import add


def test_add():
    assert add(1, 2) == 3


def test_broken_before_rehorse():
    assert add(1, 1) == 3  # a pre-existing failure the task is not about
