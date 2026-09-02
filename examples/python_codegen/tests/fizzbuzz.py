from solution import fizzbuzz


def test_multiples_of_three():
    assert fizzbuzz(3) == "fizz"
    assert fizzbuzz(9) == "fizz"


def test_multiples_of_five():
    assert fizzbuzz(5) == "buzz"
    assert fizzbuzz(20) == "buzz"


def test_multiples_of_both():
    assert fizzbuzz(15) == "fizzbuzz"
    assert fizzbuzz(45) == "fizzbuzz"


def test_everything_else_is_the_number():
    assert fizzbuzz(1) == "1"
    assert fizzbuzz(7) == "7"
