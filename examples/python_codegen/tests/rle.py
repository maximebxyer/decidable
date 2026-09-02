from solution import encode


def test_runs_are_counted():
    assert encode("aaab") == "a3b1"


def test_single_characters_still_carry_a_count():
    assert encode("abc") == "a1b1c1"


def test_empty_stays_empty():
    assert encode("") == ""
