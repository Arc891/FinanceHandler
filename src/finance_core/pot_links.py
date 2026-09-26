"""
Pot hints: context for the AI, never a category.

A purchase paid from a savings pot is covered by a transfer in from the
savings account of exactly its amount. Not every covered purchase is booked
Uit spaarpotje (bills stay Rekeningen), and as a rule the link explained 22
of 91 pot rows against 13 wrong claims (plan, rule coverage), so the AI gets
the link as a note on the row and decides.

A purchase gets a hint when exactly one transfer in from a savings account
within POT_WINDOW_DAYS has its amount, and that transfer has no other such
purchase among the candidates.
"""

from collections import defaultdict

from finance_core.tx_features import normalise_iban, tx_cents, tx_day, tx_direction

POT_WINDOW_DAYS = 7


def pot_hints(txs, candidates, savings, window=POT_WINDOW_DAYS):
    """{index into txs: hint} for the candidate purchases one transfer explains."""
    savings = {normalise_iban(i) for i in savings}
    transfers = [i for i, tx in enumerate(txs)
                 if tx_direction(tx) == "in" and normalise_iban(tx.get("counterparty_iban")) in savings]
    purchases = [i for i in candidates if tx_direction(txs[i]) == "out"]
    claims = defaultdict(list)
    for t in transfers:
        cents, day = tx_cents(txs[t]), tx_day(txs[t])
        if cents is None or day is None:
            continue
        near = [p for p in purchases
                if tx_cents(txs[p]) == cents and tx_day(txs[p]) is not None
                and abs((tx_day(txs[p]) - day).days) <= window]
        if len(near) == 1:
            claims[near[0]].append(t)
    return {p: "same amount as a transfer in from the savings account on "
               f"{tx_day(txs[ts[0]]).strftime('%d-%m-%Y')}"
            for p, ts in claims.items() if len(ts) == 1}
