#!/usr/bin/env python3
"""
Turn a real ASN CSV export into an anonymised test fixture.

Run this yourself on a real export; nobody else needs to see the input. The
output keeps everything the bot's logic depends on and scrambles everything
personal:

  kept      : row layout (all columns), booking dates, transaction codes,
              currency, sign of the amount, known merchant names, the DUO and
              salary markers that start a financial month, spaarpot references
              mapped through spaarpot_uuid_map (so the normaliser still fires)
  replaced  : amounts (random, same sign, similar size bucket), IBANs, person
              names (consistent Persoon A/B/C per distinct name), long
              reference numbers, UUID-style references, balance column
  dropped   : nothing structural; column count and order are unchanged

Usage:
    venv/bin/python scripts/make_fixture.py <real_export.csv> tests/fixtures/<name>.csv
    venv/bin/python scripts/sheet_shape.py csv tests/fixtures/<name>.csv   # verify shape

Review the output before committing it. The input file is not modified.
"""

import csv
import logging
import os
import random
import re
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from automation.data_anonymizer import TransactionAnonymizer  # noqa: E402
from config.spaarpot_uuid_map import SPAARPOT_UUID_MAP  # noqa: E402

# The anonymiser logs every name it masks; keep those out of the terminal.
logging.getLogger("automation.data_anonymizer").setLevel(logging.ERROR)

# Markers that must survive because the period splitter keys on them.
KEEP_MARKERS = re.compile(r"\b(DUO|SALARIS|SALARISBETALING|Anamata)\b", re.IGNORECASE)
IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z]{4}\d{6,}\b")
UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{8,12}\b", re.IGNORECASE)
LONG_NUM_RE = re.compile(r"\b\d{6,}\b")
# "MM. J. Naam e/o E.N. Achternaam" style joint-account names and plain names
NAME_TOKEN_RE = re.compile(r"\b(?:Mw|Dhr|Mevr|Mr|Mrs|MW\.|DHR\.)\.?\s+[A-Z][\w.]*(?:\s+[A-Z][\w.]*)*", re.IGNORECASE)

FAKE_IBAN = "NL00TEST0000000001"


class FixtureAnonymiser:
    def __init__(self, seed: int = 20260920):
        self.rng = random.Random(seed)
        self.anon = TransactionAnonymizer()
        self.person_map = {}
        self.uuid_map = {}

    def person(self, name: str) -> str:
        key = name.strip().lower()
        if key not in self.person_map:
            label = chr(ord("A") + len(self.person_map) % 26)
            self.person_map[key] = f"Persoon {label}"
        return self.person_map[key]

    def counterparty(self, name: str) -> str:
        name = name.strip()
        if not name:
            return ""
        if KEEP_MARKERS.search(name):
            return name
        cleaned = self.anon._anonymize_counterparty(name)
        if cleaned == "Private Person":
            return self.person(name)
        return cleaned

    def amount(self, raw: str) -> str:
        raw = raw.strip().replace(",", ".")
        try:
            value = float(raw)
        except ValueError:
            return raw
        sign = -1 if value < 0 else 1
        mag = abs(value)
        if mag < 10:
            new = self.rng.uniform(0.5, 9.99)
        elif mag < 100:
            new = self.rng.uniform(10, 99.99)
        elif mag < 1000:
            new = self.rng.uniform(100, 999.99)
        else:
            new = self.rng.uniform(1000, 3999.99)
        return f"{sign * new:.2f}"

    def remittance(self, text: str, counterparty_original: str) -> str:
        if not text:
            return text
        out = text
        # Spaarpot UUIDs are opaque savings-pot ids, not personal data, and the
        # CSV normaliser must still map them to a pot name. Shield them from the
        # generic UUID scrambler below, then put them back.
        shields = {}
        for i, uuid in enumerate(SPAARPOT_UUID_MAP):
            if uuid in out:
                token = f"__SPAARPOT_{i}__"
                shields[token] = uuid
                out = out.replace(uuid, token)
        out = IBAN_RE.sub(FAKE_IBAN, out)
        out = UUID_RE.sub(lambda m: self._fake_uuid(m.group(0)), out)
        # Replace the real counterparty name wherever it is echoed in the text
        if counterparty_original.strip():
            replacement = self.counterparty(counterparty_original)
            if replacement != counterparty_original.strip():
                out = out.replace(counterparty_original.strip(), replacement)
        out = NAME_TOKEN_RE.sub(lambda m: self.person(m.group(0)), out)
        out = LONG_NUM_RE.sub(lambda m: "0" * len(m.group(0)), out)
        for token, uuid in shields.items():
            out = out.replace(token, uuid)
        return out

    def _fake_uuid(self, real: str) -> str:
        if real not in self.uuid_map:
            self.uuid_map[real] = "%08x-%04x-%04x-%04x-%012x" % tuple(
                self.rng.getrandbits(b) for b in (32, 16, 16, 16, 48))
        return self.uuid_map[real]


def convert(src: str, dst: str) -> None:
    fx = FixtureAnonymiser()
    with open(src, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    out_rows = []
    for row in rows:
        if not row or len(row) < 18 or not row[0].strip():
            out_rows.append(row)
            continue
        new = list(row)
        original_cp = row[3]
        new[1] = FAKE_IBAN                      # own IBAN
        new[2] = FAKE_IBAN if row[2].strip() else ""  # counterparty IBAN
        new[3] = fx.counterparty(row[3])
        new[8] = ""                             # running balance: drop
        new[10] = fx.amount(row[10])
        new[15] = "0" * len(row[15].strip()) if row[15].strip() else row[15]  # sequence no.
        new[17] = fx.remittance(row[17], original_cp)
        if len(new) > 19:
            new[19] = row[19]                   # bank's own category label: keep
        out_rows.append(new)
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    with open(dst, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh, quoting=csv.QUOTE_MINIMAL).writerows(out_rows)
    print(f"wrote {dst}: {len(out_rows)} rows, {len(fx.person_map)} person names replaced, "
          f"{len(fx.uuid_map)} references scrambled")
    print("review it, then: venv/bin/python scripts/sheet_shape.py csv", dst)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    convert(sys.argv[1], sys.argv[2])
