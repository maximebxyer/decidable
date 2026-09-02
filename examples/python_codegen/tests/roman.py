from solution import roman


def test_single_symbols():
    assert roman(1) == "I"
    assert roman(10) == "X"
    assert roman(1000) == "M"


def test_subtractive_pairs():
    assert roman(4) == "IV"
    assert roman(9) == "IX"
    assert roman(900) == "CM"


def test_a_long_one():
    assert roman(1994) == "MCMXCIV"
