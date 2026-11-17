"""Tokenizer shared by index building and querying, so both sides always agree.

lowercase -> split on non-alphanumerics -> drop English stopwords -> light suffix stemming.
"""

import re

TOKEN = re.compile(r"[a-z0-9]+")

STOPWORDS = frozenset(
    """a about above after again against all am an and any are as at be because been before being below between both
    but by can could did do does doing down during each few for from further had has have having he her here hers
    how i if in into is it its itself just may me might more most must my no nor not now of off on once only or other
    our out over own same she should so some such than that the their them then there these they this those through
    to too under until up very was we were what when where which while who whom why will with would you your yours
    s t""".split()
)


def stem(word: str) -> str:
    """Very light English stemmer: plural and common verb endings."""
    if len(word) <= 3 or word.isdigit():
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("sses"):
        return word[:-2]
    if word.endswith("ing") and len(word) > 5:
        return word[:-3]
    if word.endswith("ed") and len(word) > 4:
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def tokenize(text: str) -> list[str]:
    return [stem(t) for t in TOKEN.findall(text.lower()) if t not in STOPWORDS]
