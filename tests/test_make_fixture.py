"""
Tests for scripts/make_fixture.py: sequence-number renumbering and row duplication.

The fixture must keep column 15 unique per transaction (so a strong dedup key
that includes it still tells transactions apart) and stable across runs (so
two fixtures cut from overlapping exports agree on the shared rows), without
carrying the bank's real numbers.
"""

import csv

import make_fixture
from make_fixture import FixtureAnonymiser, convert

from csv_rows import asn_row, write_csv


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.reader(fh))


def test_sequence_numbers_stay_unique_and_are_not_the_originals():
    fx = FixtureAnonymiser()
    real = [str(n) for n in range(979100, 979300)]
    fake = [fx.sequence(r) for r in real]
    assert len(set(fake)) == len(real)
    assert not set(fake) & set(real)
    assert all(f.isdigit() and int(f) != 0 for f in fake)


def test_sequence_numbers_are_stable_across_runs():
    assert FixtureAnonymiser().sequence("979142") == FixtureAnonymiser().sequence("979142")


def test_empty_sequence_number_stays_empty():
    assert FixtureAnonymiser().sequence("") == ""
    assert FixtureAnonymiser().sequence("   ") == ""


def test_convert_renumbers_column_15(tmp_path):
    src = write_csv(tmp_path / "real.csv", [asn_row(seq="1001"), asn_row(seq="1002")])
    dst = tmp_path / "fixture.csv"
    convert(src, str(dst))
    out = read_csv(dst)
    assert len(out) == 2
    seqs = [r[15] for r in out]
    assert len(set(seqs)) == 2
    assert "1001" not in seqs and "1002" not in seqs


def test_duplicate_row_inserts_an_identical_copy_with_its_own_sequence_number(tmp_path):
    src = write_csv(tmp_path / "real.csv", [
        asn_row(seq="1"), asn_row(seq="2", counterparty="Albert Heijn"), asn_row(seq="3"),
    ])
    dst = tmp_path / "fixture.csv"
    convert(src, str(dst), duplicate_rows=[2])
    out = read_csv(dst)
    assert len(out) == 4
    original, copy = out[1], out[2]
    assert copy[:15] == original[:15]
    assert copy[16:] == original[16:]
    assert copy[15] != original[15]
    assert len({r[15] for r in out}) == 4


def test_duplicate_row_out_of_range_is_an_error(tmp_path):
    src = write_csv(tmp_path / "real.csv", [asn_row(seq="1")])
    try:
        convert(src, str(tmp_path / "fixture.csv"), duplicate_rows=[5])
    except ValueError as exc:
        assert "5" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_cli_accepts_duplicate_row_flag(tmp_path):
    src = write_csv(tmp_path / "real.csv", [asn_row(seq="1"), asn_row(seq="2")])
    dst = tmp_path / "fixture.csv"
    assert make_fixture.main([src, str(dst), "--duplicate-row", "1"]) == 0
    assert len(read_csv(dst)) == 3
