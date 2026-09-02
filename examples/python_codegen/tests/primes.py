from solution import primes_below


def test_small_range():
    assert primes_below(10) == [2, 3, 5, 7]


def test_nothing_below_two():
    assert primes_below(2) == []


def test_excludes_the_bound():
    assert primes_below(7) == [2, 3, 5]
