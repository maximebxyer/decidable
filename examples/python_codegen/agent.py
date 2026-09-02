"""A canned agent, so the reproduction is byte-identical on every machine.

A real agent would call a model here. This one looks answers up in a dict, which
is all the harness needs: an ``Agent`` is anything callable that maps a task to
an artifact. Deliberately, no provider SDK, no API key, no network.

Each answer below breaks at a different point in the verifier stack, so the
report shows a taxonomy instead of a column of passes.
"""

from __future__ import annotations

from typing import Any

# Correct.
FIZZBUZZ = """\
def fizzbuzz(n: int) -> str:
    if n % 15 == 0:
        return "fizzbuzz"
    if n % 3 == 0:
        return "fizz"
    if n % 5 == 0:
        return "buzz"
    return str(n)
"""

# SYNTACTIC: an unterminated dict literal. Never even parses.
ROMAN = """\
def roman(n: int) -> str:
    numerals = {1000: "M", 900: "CM", 500: "D", 400: "CD",
    out = ""
    for value, symbol in numerals.items():
        while n >= value:
            out += symbol
            n -= value
    return out
"""

# STATIC (mypy): parses fine, but returns a str where bool is declared.
ANAGRAM = """\
def is_anagram(a: str, b: str) -> bool:
    left = sorted(a.replace(" ", "").lower())
    right = sorted(b.replace(" ", "").lower())
    return "".join(left) == "".join(right) and "yes"
"""

# STATIC (ruff): type-checks, but imports something it never uses.
PRIMES = """\
import math
import os


def primes_below(n: int) -> list[int]:
    return [
        candidate
        for candidate in range(2, n)
        if all(candidate % d for d in range(2, int(math.sqrt(candidate)) + 1))
    ]
"""

# DYNAMIC: type-checks and lints, then divides by zero at import time.
BALANCED = """\
PAIRS = {")": "(", "]": "[", "}": "{"}
LIMIT = 100 // 0


def is_balanced(text: str) -> bool:
    stack: list[str] = []
    for character in text:
        if character in "([{":
            stack.append(character)
        elif character in PAIRS and (not stack or stack.pop() != PAIRS[character]):
            return False
    return not stack
"""

# BEHAVIOURAL: parses, type-checks, lints and runs. Just wrong.
# It collapses each run to one character and never emits the count.
RLE = """\
def encode(text: str) -> str:
    out: list[str] = []
    for index, character in enumerate(text):
        if index == 0 or character != text[index - 1]:
            out.append(character)
    return "".join(out)
"""

ANSWERS = {
    "fizzbuzz": FIZZBUZZ,
    "roman": ROMAN,
    "anagram": ANAGRAM,
    "primes": PRIMES,
    "balanced": BALANCED,
    "rle": RLE,
}


def agent(task: Any) -> str:
    """Map a task to the answer this fictional model gave for it."""
    return ANSWERS[task.id]
