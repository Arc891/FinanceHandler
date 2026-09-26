"""
What a bank row holds beyond its name and text, for rules to check.

Direction, the bank's transaction code, a time of day in the remittance text
(iDEAL rows carry one, card payments do not), weekday or weekend, the amount,
the words of the text, and the role of the counterparty's account from
ACCOUNT_ROLES in the local config. Shared by the production rules and the
rule analysis (scripts/rule_coverage.py), so both read a row the same way.
"""

import re
from datetime import date

from finance_core.config_access import setting
from finance_core.row_tuple import canonical_date

TIME_OF_DAY = re.compile(r"(?<![\d:])([01]\d|2[0-3]):[0-5]\d(?![\d:])")
CODE_SHAPE = re.compile(r"^[A-Z]{2,4}$")
WORD = re.compile(r"[a-z]{3,}")


def remittance_text(tx) -> str:
    return " ".join(tx.get("remittance_information") or [])


def tx_day(tx):
    try:
        return date.fromisoformat(canonical_date(tx.get("booking_date", "")))
    except (TypeError, ValueError):
        return None


def tx_direction(tx):
    return "in" if tx.get("credit_debit_indicator") == "CRDT" else "out"


def tx_code(tx):
    """The bank's transaction code (BEA, IDB, ...), or `other` if not code-shaped."""
    parts = ((tx.get("bank_transaction_code") or {}).get("description") or "").split()
    return parts[-1] if parts and CODE_SHAPE.match(parts[-1]) else "other"


def tx_hour(tx):
    """The hour of a time of day in the remittance text, or None."""
    m = TIME_OF_DAY.search(remittance_text(tx))
    return int(m.group(1)) if m else None


def tx_weekend(tx):
    day = tx_day(tx)
    return None if day is None else day.weekday() >= 5


def tx_year(tx):
    day = tx_day(tx)
    return None if day is None else day.year


def tx_amount(tx):
    """The amount without its sign, in euros, or None."""
    try:
        return round(abs(float(tx["transaction_amount"]["amount"])), 2)
    except (KeyError, TypeError, ValueError):
        return None


def tx_cents(tx):
    amount = tx_amount(tx)
    return None if amount is None else round(amount * 100)


def tx_words(tx):
    return set(WORD.findall(remittance_text(tx).lower()))


def normalise_iban(iban) -> str:
    return re.sub(r"\s+", "", iban or "").upper()


ROLES = ("savings", "partner_personal", "user_personal")
_given_roles = None


def use_account_roles(roles):
    """Answer `roles` instead of the config's (the eval reads them from a
    private file); None goes back to the config."""
    global _given_roles
    _given_roles = roles


def account_roles() -> dict:
    """ACCOUNT_ROLES from the local config: {role: [iban, ...]}; empty without one."""
    if _given_roles is not None:
        return _given_roles
    return setting("ACCOUNT_ROLES", {}) or {}


def account_role(tx):
    """The role of the counterparty's account (`savings`, `partner_personal`, ...), or None."""
    iban = normalise_iban(tx.get("counterparty_iban"))
    if not iban:
        return None
    for role, ibans in account_roles().items():
        if iban in {normalise_iban(i) for i in ibans}:
            return role
    return None
