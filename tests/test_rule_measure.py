"""
Tests for step 3 of the rule work: measuring the local rules before they go live.

`eval_categoriser --rules --local-rules PATH --account-roles PATH` scores the
regex pass with the household's own rules and account roles, as the bot runs
them, and the AI run gets the same rules. A local rule is printed by its
group id and line, never by its pattern (patterns hold names); a marked rule
counts as a row that needs the user. `--amount-cuts ID=a,b,c` shows, for one
counterparty group, what a rule "from this amount up" would write at each
cut. The roles file holds account numbers and is never echoed. Without
--local-rules the analysis uses no local rules at all, so group ids stay
those of the draft they were chosen from. All rows and numbers are synthetic.
"""

import asyncio

import pytest

import eval_categoriser as ev
import rule_coverage as rc
from finance_core import local_rules as lr
from finance_core import tx_features
from finance_core.categorization_engine import CategorizationEngine
from finance_core.categorization_rules import first_matching_rule
from fakes import expense_tx, income_tx

SECRET_NAME = "Jolanda Vermeulen"
SAVINGS = "NL99SAVE0000000001"
HERS = "NL98HERS0000000002"
PERSONAL = "NL97PERS0000000003"
VRIJ = "Persoonlijk vrij geld"
VALID = {"expenses": {"Boodschappen", "Cadeautjes", "Huishouden", "Persoonlijke verzorging", VRIJ},
         "income": {"Gemeente", "Salaris", "Gift"}}


@pytest.fixture(autouse=True)
def config_roles(monkeypatch):
    """No roles from a local config; any override the test sets is undone."""
    monkeypatch.setattr(tx_features, "setting", lambda name, default=None: default)
    yield
    tx_features.use_account_roles(None)


def tx(date="04-03-2025", amount="10.00", name="Shop", rem="", out=True, iban=""):
    make = expense_tx if out else income_tx
    t = make(date_str=date, amount=f"-{amount}" if out else amount, name=name, rem=rem)
    t = {k: v for k, v in t.items() if k not in ("description", "category")}
    t["counterparty_iban"] = iban
    return t


def row(t, category):
    d, m, y = t["booking_date"].split("-")
    block = "income" if t["credit_debit_indicator"] == "CRDT" else "expenses"
    amount = t["transaction_amount"]["amount"].lstrip("-")
    return ev.SheetRow(f"{m}/{y}", block, f"{y}-{m}-{d}", amount, category, False)


def local(*lines):
    return lr.parse_local_rules("\n".join("\t".join(line) for line in lines))


def coverage(data, **kwargs):
    txs = [t for t, _ in data]
    m = ev.match_rows(txs, [row(t, c) for t, c in data], VALID, {})
    return rc.rule_coverage(m.records, m.truths, txs, spaarpot_names=[], **kwargs)


# ── a local rule's name in reports ──────────────────────────────────────────

def test_a_local_rule_is_named_by_its_group_id_and_line():
    rules = local(("# header",), ("out", r"\bjolanda\b", "-", "Cadeautjes", "-", "Cadeau", "N07"))
    assert first_matching_rule(tx(name=SECRET_NAME), rules).label == "local N07 line 2"


def test_a_source_that_is_no_group_id_stays_out_of_the_name():
    """The source column is free text the user may edit: only an id is shown."""
    rules = local(("out", r"\bjolanda\b", "-", "Cadeautjes", "-", "Cadeau", "Jolanda"))
    assert first_matching_rule(tx(name=SECRET_NAME), rules).label == "local line 1"
    rules = local(("out", r"\bjolanda\b", "-", "Cadeautjes", "-", "Cadeau"))
    assert first_matching_rule(tx(name=SECRET_NAME), rules).label == "local line 1"


def test_a_rule_from_constants_has_no_label():
    assert first_matching_rule(tx(name="PICNIC"), []).label is None


# ── the engine takes the rules it is given ──────────────────────────────────

GIVEN = [("out", r"\bjolanda\b", "-", "Cadeautjes", "-", "Cadeau")]
CONFIGURED = [("out", r"\bjolanda\b", "-", "Huishouden", "-", "Configured")]


def configured_file(monkeypatch):
    monkeypatch.setattr("finance_core.categorization_engine.default_local_rules",
                        lambda: local(*CONFIGURED))


def test_the_engine_uses_the_local_rules_it_was_given(monkeypatch):
    configured_file(monkeypatch)
    engine = CategorizationEngine(local_rules=local(*GIVEN))
    (batch,) = asyncio.run(engine.batch_categorize([tx(name=SECRET_NAME)]))
    single = asyncio.run(engine.categorize(tx(name=SECRET_NAME)))
    assert (batch.category, single.category) == ("Cadeautjes", "Cadeautjes")


def test_an_engine_given_no_local_rules_uses_none(monkeypatch):
    configured_file(monkeypatch)
    engine = CategorizationEngine(local_rules=[])
    (batch,) = asyncio.run(engine.batch_categorize([tx(name=SECRET_NAME)]))
    assert batch.method != "regex"


def test_the_bot_engine_reads_the_configured_file(monkeypatch):
    configured_file(monkeypatch)
    (batch,) = asyncio.run(CategorizationEngine().batch_categorize([tx(name=SECRET_NAME)]))
    assert batch.category == "Huishouden"


def test_the_eval_engine_gets_the_eval_rules():
    rules = local(*GIVEN)
    made = []
    engine = ev.build_engine("sonnet", rules, make_ai=lambda model: made.append(model) or object())
    assert engine.local_rules is rules and engine.ai_enabled and made == ["sonnet"]


# ── the account roles file ──────────────────────────────────────────────────

def test_the_roles_file_gives_each_role_its_accounts(tmp_path):
    path = tmp_path / "roles.txt"
    path.write_text("# my accounts\nsavings NL99 SAVE 0000 0000 01\n\npartner_personal nl98hers0000000002\n"
                    f"user_personal {PERSONAL}\nuser_personal NL96MINE0000000004\n")
    assert ev.load_account_roles(str(path)) == {
        "savings": [SAVINGS], "partner_personal": [HERS],
        "user_personal": [PERSONAL, "NL96MINE0000000004"]}


@pytest.mark.parametrize("text, problem", [
    ("saving NL99SAVE0000000001\n", "role"),
    ("savings\n", "IBAN"),
    ("savings NL99-SAVE\n", "IBAN"),
    ("savings NL99SAVE0000000001\nuser_personal NL99SAVE0000000001\n", "twice"),
])
def test_a_bad_roles_line_stops_the_run_by_line_number_only(tmp_path, text, problem):
    path = tmp_path / "roles.txt"
    path.write_text("# header\n" + text)
    with pytest.raises(ev.InputError) as err:
        ev.load_account_roles(str(path))
    message = str(err.value)
    assert "line 2" in message or "line 3" in message
    assert problem in message and "SAVE" not in message and "saving " not in message


def test_a_missing_roles_file_stops_the_run(tmp_path):
    with pytest.raises(ev.InputError):
        ev.load_account_roles(str(tmp_path / "absent.txt"))


def test_the_roles_given_reach_the_rules():
    salaris = tx(name="Her", rem="salaris", out=False, iban=HERS)
    assert first_matching_rule(salaris, []).category.value == "Salaris"
    tx_features.use_account_roles({"partner_personal": [HERS]})
    assert first_matching_rule(salaris, []).category.value == "Gemeente"
    tx_features.use_account_roles(None)
    assert tx_features.account_role(salaris) is None


# ── the analysis with local rules ───────────────────────────────────────────

RULES = [
    ("out", r"\bjolanda\W+vermeulen\b", "-", "Cadeautjes", "-", "Cadeau", "N07"),
    ("out", r"\bkruidvat\b", "-", "Huishouden", "?", "Kruidvat", "N02"),
    ("out", r"\beigen\b", "-", "ai", "-", "-", "N05"),
]
DATA = [
    *[(tx(f"0{m}-0{m}-2025", "15.00", name=SECRET_NAME), "Cadeautjes") for m in (3, 4, 5)],
    (tx("06-03-2025", "4.50", name="Kruidvat 12"), "Huishouden"),
    (tx("07-04-2025", "5.50", name="KRUIDVAT"), "Persoonlijke verzorging"),
    (tx("08-03-2025", "12.34", name="Eigen Rekening"), "Boodschappen"),
    (tx("09-03-2025", "11.00", name="JUMBO UTRECHT"), "Boodschappen"),
]


def test_local_rules_are_scored_under_their_names_not_their_patterns():
    cov = coverage(DATA, local_rules=local(*RULES))
    assert cov["rules"]["local N07 line 1"]["hits"] == 3
    assert cov["rules"]["local N07 line 1"]["correct"] == 3
    assert cov["rules"]["local N02 line 2"]["hits"] == 2
    assert not any("jolanda" in key or "kruidvat" in key for key in cov["rules"])


def test_a_marked_rule_counts_as_a_row_that_needs_the_user():
    p = coverage(DATA, local_rules=local(*RULES))["projection"]
    # By rule: Jumbo and the three presents; marked: both Kruidvat rows, the
    # wrong one included, since the user checks it; the `ai` line: to the AI.
    assert p["today"] == dict(rules=4, rules_wrong=0, plain=0, plain_wrong=0, marked=2, ai=1)


def test_the_local_rules_summary_is_counts_only():
    cov = coverage(DATA, local_rules=local(*RULES))
    assert cov["local"] == dict(loaded=3, caught=5, correct=4, marked=2)
    out = "\n".join(rc.format_rule_coverage(cov))
    assert "local rules: 3 loaded; 5 rows caught (4 correct), 2 of them marked" in out
    assert "'local N07 line 1': 3" in out
    for secret in (SECRET_NAME, "Vermeulen", "jolanda", "kruidvat", "Kruidvat", "eigen", "Cadeau\t",
                   "12.34", "15.00"):
        assert secret not in out


def test_without_local_rules_the_analysis_uses_none_even_if_a_file_is_configured(monkeypatch):
    """Run A: the group ids must be those of the draft the rules came from."""
    monkeypatch.setattr("finance_core.categorization_rules.default_local_rules", lambda: local(*RULES))
    cov = coverage(DATA)
    assert cov["local"] is None
    assert not any(key.startswith("local") for key in cov["rules"])
    assert sum(cov["uncovered"].values()) == 6


# ── amount cuts for one group ───────────────────────────────────────────────

def own(date, amount, category):
    return tx(date, amount, name="Eigen Rekening", iban=PERSONAL), category


CUT_DATA = [
    own("01-01-2025", "150.00", VRIJ), own("01-02-2025", "150.00", VRIJ),
    own("01-03-2025", "150.00", VRIJ), own("01-04-2025", "125.00", VRIJ),
    own("01-05-2025", "120.00", VRIJ), own("01-06-2025", "120.00", VRIJ),
    own("10-06-2025", "110.00", "Boodschappen"), own("11-07-2025", "20.00", "Boodschappen"),
    own("12-08-2025", "30.00", "Huishouden"),
    # Before the window: not counted.
    own("01-06-2024", "200.00", VRIJ),
]


def cut_coverage(cuts):
    cov = coverage(CUT_DATA, since="01/2025", cuts=cuts)
    (group,) = cov["name_groups"]
    return cov, group["id"]


def test_each_cut_counts_the_rows_from_it_up_and_below_it_in_the_window():
    _, gid = cut_coverage({})
    cov, _ = cut_coverage({gid: [100.0, 125.0]})
    got = cov["cuts"][gid]
    assert got["rows"] == 9
    low, high = got["cuts"]
    assert (low["cut"], sum(low["above"].values()), low["above"][VRIJ]) == (100.0, 7, 6)
    assert low["below"] == {"Boodschappen": 1, "Huishouden": 1}
    # A row at the cut exactly is from the cut up.
    assert (sum(high["above"].values()), high["above"][VRIJ]) == (4, 4)
    assert high["below"] == {VRIJ: 2, "Boodschappen": 2, "Huishouden": 1}


def test_an_unknown_group_id_is_reported_not_guessed():
    cov, _ = cut_coverage({"N99": [100.0]})
    assert cov["cuts"]["N99"] is None
    assert "N99: no such group" in "\n".join(rc.format_rule_coverage(cov))


def test_the_printed_cuts_hold_counts_and_categories_only():
    _, gid = cut_coverage({})
    cov, _ = cut_coverage({gid: [100.0, 125.0]})
    out = "\n".join(rc.format_rule_coverage(cov))
    assert f"{gid}: 9 rows in the window" in out
    assert f"from 125: 4 rows, {VRIJ} 4/4 (100%); below: 5 rows:" in out
    for secret in (PERSONAL, "Eigen", "eigen", "150.00", "120.00", "110.00", "2025-0"):
        assert secret not in out


@pytest.mark.parametrize("arg, expected", [
    ("N07=100,125,150", ("N07", [100.0, 125.0, 150.0])),
    ("I03=99.5", ("I03", [99.5])),
])
def test_the_cut_argument_reads_a_group_and_amounts(arg, expected):
    assert ev.parse_cuts(arg) == expected


@pytest.mark.parametrize("arg", ["N07", "N07=", "N07=abc", "Jolanda=100", "N07=100,-5"])
def test_a_bad_cut_argument_is_refused(arg):
    import argparse
    with pytest.raises(argparse.ArgumentTypeError):
        ev.parse_cuts(arg)


# ── end to end ──────────────────────────────────────────────────────────────

class FakeGc:
    def __init__(self, blocks):
        self.blocks = blocks

    def list_spreadsheet_files(self):
        return [{"name": "Maandelijks Budget 03/2025", "id": "x"}]

    def open_by_key(self, key):
        blocks = self.blocks

        class Book:
            def values_batch_get(self, ranges, params=None):
                return {"valueRanges": [{"values": blocks["B1:E"]}, {"values": blocks["G1:J"]}]}
        return Book()


@pytest.fixture
def one_month(monkeypatch):
    txs = [tx("17-03-2025", "10.00", name=SECRET_NAME), tx("18-03-2025", "3.10", name="Hema")]
    blocks = {"B1:E": [["Date"], [45733, 10.0, "d", "Cadeautjes"], [45734, 3.1, "d", "Huishouden"]],
              "G1:J": []}
    monkeypatch.setattr(ev, "load_exports", lambda paths: (txs, 0))
    monkeypatch.setattr(ev, "service_account_client", lambda p: FakeGc(blocks))
    monkeypatch.setattr(ev, "MIN_INTERVAL", 0.0)
    monkeypatch.setattr(rc, "spaarpot_names", lambda: [])


def test_the_rules_run_loads_the_rules_and_roles_and_prints_counts_only(one_month, tmp_path, capsys):
    rules = tmp_path / "local_rules.tsv"
    rules.write_text("\t".join(RULES[0]) + "\n")
    roles = tmp_path / "roles.txt"
    roles.write_text(f"savings {SAVINGS}\npartner_personal {HERS}\n")
    code = ev.main(["--rules", "--local-rules", str(rules), "--account-roles", str(roles),
                    "--years", "2025", "--amount-cuts", "N01=5", "x.csv"])
    out = capsys.readouterr().out
    assert code == 0
    assert "local rules: 1 loaded" in out
    assert "account roles: savings 1, partner_personal 1, user_personal 0" in out
    assert "local N07 line 1" in out
    for secret in (SECRET_NAME, "jolanda", SAVINGS, HERS, "SAVE", "10.00"):
        assert secret not in out


def test_a_missing_rules_file_stops_the_run_with_a_plain_message(one_month, tmp_path, capsys):
    code = ev.main(["--rules", "--local-rules", str(tmp_path / "absent.tsv"), "--years", "2025", "x.csv"])
    out = capsys.readouterr().out
    assert code == 2 and "stopped: the local rules file does not exist" in out


def test_a_bad_rules_line_stops_the_run_with_its_line_number(one_month, tmp_path, capsys):
    rules = tmp_path / "local_rules.tsv"
    rules.write_text(f"out\t{SECRET_NAME}\t-\tNo such category\t-\tX\n")
    code = ev.main(["--rules", "--local-rules", str(rules), "--years", "2025", "x.csv"])
    out = capsys.readouterr().out
    assert code == 2 and "line 1" in out and "category" in out and SECRET_NAME not in out


def test_amount_cuts_need_the_rules_run(one_month, capsys):
    with pytest.raises(SystemExit):
        ev.main(["--dry-run", "--amount-cuts", "N01=5", "x.csv"])
