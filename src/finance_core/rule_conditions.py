"""
The condition a rule checks beyond its pattern, written as short words.

`-` holds always. Otherwise words separated by spaces, all of which must hold:

    code=BEA  code!=BEA          the bank's transaction code
    amount>=100  amount<12.50    the amount without its sign
    amount=100.00/125.00         one of these amounts (a fixed transfer)
    amount!=100.00/125.00        none of them
    hour>=12.5  hour<12.5        a time of day in the text (iDEAL rows)
    hour=none                    no time of day in the text
    weekend  weekday
    word=premie  word!=premie    a word of three letters or more in the text
    role=savings  role!=savings  the role of the counterparty's account
"""

import re

from finance_core.tx_features import (
    account_role, tx_amount, tx_code, tx_hour, tx_weekend, tx_words,
)

_NUMBER = r"\d+(?:\.\d+)?"
_TERM = re.compile(
    r"(?P<field>code|amount|hour|word|role)(?P<op>>=|<|!=|=)(?P<value>\S+)|(?P<flag>weekend|weekday)")


def _number(text):
    if not re.fullmatch(_NUMBER, text):
        raise ValueError("not a number")
    return float(text)


def _amounts(text):
    return {round(_number(a), 2) for a in text.split("/")}


def _term(word):
    m = _TERM.fullmatch(word)
    if not m:
        raise ValueError("unknown condition")
    if m["flag"]:
        want = m["flag"] == "weekend"
        return lambda tx: tx_weekend(tx) is want
    field, op, value = m["field"], m["op"], m["value"]
    if field in ("amount", "hour") and op in (">=", "<"):
        cut = _number(value)
        get = tx_amount if field == "amount" else tx_hour
        if op == ">=":
            return lambda tx: (v := get(tx)) is not None and v >= cut
        return lambda tx: (v := get(tx)) is not None and v < cut
    if op not in ("=", "!="):
        raise ValueError("this field takes = or !=")
    if field == "amount":
        amounts = _amounts(value)
        test = lambda tx: tx_amount(tx) in amounts               # noqa: E731
    elif field == "hour":
        if value != "none":
            raise ValueError("hour takes >=, < or =none")
        test = lambda tx: tx_hour(tx) is None                    # noqa: E731
    elif field == "code":
        if not re.fullmatch(r"[A-Z]{2,4}|other", value):
            raise ValueError("a code is 2-4 capitals, or `other`")
        test = lambda tx: tx_code(tx) == value                   # noqa: E731
    elif field == "word":
        if not re.fullmatch(r"[a-z]{3,}", value):
            raise ValueError("a word is 3 or more lower-case letters")
        test = lambda tx: value in tx_words(tx)                  # noqa: E731
    else:
        if not re.fullmatch(r"[a-z_]+", value):
            raise ValueError("a role is lower-case letters and _")
        test = lambda tx: account_role(tx) == value              # noqa: E731
    return test if op == "=" else (lambda tx: not test(tx))


def parse_when(text):
    """A predicate over a transaction; ValueError when the text is not a condition."""
    text = (text or "").strip()
    if text in ("", "-"):
        return lambda tx: True
    terms = [_term(word) for word in text.split()]
    return lambda tx: all(term(tx) for term in terms)
