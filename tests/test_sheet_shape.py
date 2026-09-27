"""
Tests for scripts/sheet_shape.py (Phase 4 step 1): the structure-only
inspection tool, with the service account and read-only scopes.

`--folder ID` prints the Drive tree under a folder: folder names, spreadsheet
names and ids, whether the account can edit each. `--summary` prints each
sheet's Summary formulas (a number or a text inside a formula is masked, so
a hand-typed amount cannot show), the category labels of the two tables, and
whether the starting balance L8 is filled; never a rendered value. Neither
reads the retired GOOGLE_CREDENTIALS_PATH / GSHEET_TAB config keys. All data
is synthetic.
"""

import pytest

import sheet_shape as ss

FOLDER = "root-folder"
FOLDER_MIME = "application/vnd.google-apps.folder"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"


def item(fid, name, mime=SHEET_MIME, edit=True):
    return {"id": fid, "name": name, "mimeType": mime, "capabilities": {"canEdit": edit}}


TREE = {
    FOLDER: [item("s-0426", "Maandelijks Budget 04/2026"), item("f-2025", "2025", FOLDER_MIME),
             item("s-tpl", "Template Maandelijks Budget xx/2026", edit=False),
             item("d-1", "notes.pdf", "application/pdf")],
    "f-2025": [item("f-bet", "Betaalrekening", FOLDER_MIME), item("s-1225", "Maandelijks Budget 12/2025")],
    "f-bet": [item("s-1125", "Maandelijks Budget 11/2025")],
}


def test_the_folder_tree_lists_folders_then_sheets_with_ids_and_edit_rights():
    lines = ss.format_tree(ss.folder_tree(lambda fid: TREE.get(fid, []), FOLDER, "Financiën"))
    assert lines == [
        "Financiën/",
        "  2025/",
        "    Betaalrekening/",
        "      Maandelijks Budget 11/2025  s-1125  can edit",
        "    Maandelijks Budget 12/2025  s-1225  can edit",
        "  Maandelijks Budget 04/2026  s-0426  can edit",
        "  Template Maandelijks Budget xx/2026  s-tpl  read only",
        "  notes.pdf  (not a spreadsheet)",
        "3 folders, 4 spreadsheets, 1 other file",
    ]


def test_a_folder_seen_twice_is_listed_once():
    """Drive allows a folder in two parents; the walk must not loop."""
    loop = {FOLDER: [item("f-a", "a", FOLDER_MIME)], "f-a": [item(FOLDER, "back", FOLDER_MIME)]}
    lines = ss.format_tree(ss.folder_tree(lambda fid: loop.get(fid, []), FOLDER, "top"))
    assert lines[-1] == "2 folders, 0 spreadsheets, 0 other files"


def test_the_drive_listing_follows_page_tokens():
    pages = [{"files": [item("a", "A")], "nextPageToken": "t2"}, {"files": [item("b", "B")]}]
    seen = []

    def request(params):
        seen.append(params.get("pageToken"))
        return pages[len(seen) - 1]
    assert [f["id"] for f in ss.list_children(request, FOLDER)] == ["a", "b"]
    assert seen == [None, "t2"]


# ── the Summary tab ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("formula, shown", [
    ("=sum(E27:E)", "=sum(E27:E)"),
    ("=D17+(I22-C22)", "=D17+(I22-C22)"),
    ('=IF(ISBLANK($B45); ""; SUMIF(Transactions!$E:$E;$B45;Transactions!$C:$C))',
     '=IF(ISBLANK($B45); ""; SUMIF(Transactions!$E:$E;$B45;Transactions!$C:$C))'),
    ("=L8+1234,56", "=L8+#"),
    ("=150*12", "=#*#"),
    # 0 and 1 are logic, not amounts; other numbers are masked.
    ('=IF(B3="Jolanda"; 5; 0)', '=IF(B3="…"; #; 0)'),
])
def test_a_formula_keeps_its_cell_references_but_masks_numbers_and_texts(formula, shown):
    assert ss.mask_formula(formula) == shown


class FakeSheet:
    title = "Maandelijks Budget 04/2026"

    def __init__(self, formulas, l8=True):
        self.formulas = formulas
        self.l8 = l8
        self.calls = []

    def fetch_sheet_metadata(self):
        return {"properties": {"locale": "nl_NL", "timeZone": "Europe/Monaco", "autoRecalc": "ON_CHANGE"},
                "sheets": [{"properties": {"title": "Summary"}}, {"properties": {"title": "Transactions"}}]}

    def values_get(self, rng, params=None):
        self.calls.append((rng, params))
        return {"values": self.formulas}


def summary_grid():
    grid = [[""] * 12 for _ in range(46)]
    grid[7][11] = "1234.56"                          # L8, the starting balance: a value
    grid[16][4] = "=D17+(I22-C22)"                   # E17
    grid[16][3] = "=if(isblank(L8);0;L8)"            # D17
    grid[25][4] = "=sum(E27:E)"                      # E26
    grid[27][1] = "Boodschappen"                     # B28
    grid[44][1] = "! Nog in te delen !"              # B45
    grid[44][4] = '=IF(ISBLANK($B45); ""; SUMIF(Transactions!$E:$E;$B45;Transactions!$C:$C))'
    grid[27][7] = "Salaris"                          # H28
    grid[30][2] = "Jolanda's verjaardag 150"         # C31: a note, not a category label
    return grid


def test_the_summary_prints_formulas_labels_and_whether_l8_is_filled():
    sheet = FakeSheet(summary_grid())
    out = "\n".join(ss.summary_lines(sheet))
    assert "locale nl_NL, time zone Europe/Monaco, recalculation ON_CHANGE" in out
    assert "E26: =sum(E27:E)" in out and "E17: =D17+(I22-C22)" in out and "D17: =if(isblank(L8);0;L8)" in out
    assert "E45: =IF(ISBLANK($B45)" in out
    assert "expense categories B27:B45: 2 labels, first Boodschappen (B28), last ! Nog in te delen ! (B45)" in out
    assert "income categories H27:H44: 1 label, first Salaris (H28), last Salaris (H28)" in out
    assert "L8 (starting balance): filled" in out
    # Read as formulas: a rendered value never comes back.
    assert all(params == {"valueRenderOption": "FORMULA"} for _, params in sheet.calls)


def test_the_summary_never_prints_a_value_or_a_note():
    out = "\n".join(ss.summary_lines(FakeSheet(summary_grid())))
    for secret in ("1234", "Jolanda", "verjaardag", "150"):
        assert secret not in out


def test_an_empty_l8_is_reported_as_empty():
    grid = summary_grid()
    grid[7][11] = ""
    assert "L8 (starting balance): empty" in "\n".join(ss.summary_lines(FakeSheet(grid)))


# ── credentials ─────────────────────────────────────────────────────────────

def test_the_tool_only_reads():
    assert ss.SCOPES == ("https://www.googleapis.com/auth/spreadsheets.readonly",
                         "https://www.googleapis.com/auth/drive.readonly")


def test_the_key_file_comes_from_the_argument_not_the_config(monkeypatch, tmp_path):
    import sys
    monkeypatch.setitem(sys.modules, "config.config_settings", None)   # importing it would fail
    used = []
    monkeypatch.setattr(ss, "service_account_client", lambda path: used.append(path) or FakeGc())
    assert ss.main(["sheets", "--credentials", str(tmp_path / "key.json"), "--folder", FOLDER]) == 0
    assert used == [str(tmp_path / "key.json")]


def test_the_default_key_file_is_the_one_in_src_config(monkeypatch):
    used = []
    monkeypatch.setattr(ss, "service_account_client", lambda path: used.append(path) or FakeGc())
    ss.main(["sheets", "--folder", FOLDER])
    assert used == [ss.DEFAULT_KEY]
    assert ss.DEFAULT_KEY.endswith("src/config/google_service_account.json")


class FakeGc:
    class http_client:
        @staticmethod
        def request(method, endpoint, params=None):
            class Response:
                @staticmethod
                def json():
                    if params["q"].startswith("'root-folder'"):
                        return {"files": [item("s-1", "Maandelijks Budget 04/2026")]}
                    return {"files": []}
            return Response()

    def get_file_drive_metadata(self, fid):
        return {"name": "Financiën"}


def test_the_folder_mode_prints_the_tree(monkeypatch, capsys):
    monkeypatch.setattr(ss, "service_account_client", lambda path: FakeGc())
    assert ss.main(["sheets", "--folder", FOLDER]) == 0
    out = capsys.readouterr().out
    assert "Financiën/" in out and "  Maandelijks Budget 04/2026  s-1  can edit" in out


def test_flags_may_come_before_the_sheet_names(monkeypatch, capsys):
    class Gc(FakeGc):
        def list_spreadsheet_files(self):
            return [{"name": "Maandelijks Budget 04/2026", "id": "s-1"}, {"name": "Other", "id": "s-2"}]

        def open_by_key(self, key):
            assert key == "s-1"
            return FakeSheet(summary_grid())
    monkeypatch.setattr(ss, "service_account_client", lambda path: Gc())
    assert ss.main(["sheets", "--summary", "Maandelijks Budget 04/2026"]) == 0
    assert "== SUMMARY Maandelijks Budget 04/2026" in capsys.readouterr().out


def test_rows_with_the_same_formula_are_printed_as_one_run():
    grid = summary_grid()
    for r in (28, 29, 30):
        grid[r - 1][10] = f"=if(isblank($H{r}); \"\"; sumif(Transactions!$J:$J;$H{r};Transactions!$H:$H))"
    grid[30][10] = "=K29"                            # K31 breaks the run
    out = ss.summary_lines(FakeSheet(grid))
    assert '  K28:K30: =if(isblank($H{r}); ""; sumif(Transactions!$J:$J;$H{r};Transactions!$H:$H))' in out
    assert "  K31: =K29" in out
    # A single row keeps its own numbers.
    assert "  E45: =IF(ISBLANK($B45); \"\"; SUMIF(Transactions!$E:$E;$B45;Transactions!$C:$C))" in out
