from solution import is_balanced


def test_balanced_pairs():
    assert is_balanced("()")
    assert is_balanced("([]{})")


def test_unbalanced():
    assert not is_balanced("(]")
    assert not is_balanced("(()")


def test_empty_is_balanced():
    assert is_balanced("")
