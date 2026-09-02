from solution import is_anagram


def test_plain_anagrams():
    assert is_anagram("listen", "silent")
    assert not is_anagram("hello", "world")


def test_case_and_spaces_are_ignored():
    assert is_anagram("Dormitory", "dirty room")


def test_the_result_is_a_bool():
    assert is_anagram("ab", "ba") is True
    assert is_anagram("ab", "cd") is False
