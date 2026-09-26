"""
The household's own rules: src/config/local_rules.tsv (LOCAL_RULES_PATH).

The file is local and git-ignored, because its patterns hold names and its
conditions amounts. scripts/apply_rule_draft.py writes it from the decisions
the user made in the rule draft; the user may edit it afterwards. One rule
per line, tab-separated, `#` lines and blank lines skipped:

    direction  pattern  when  category  mark  description  [source]

- direction: `in` or `out`;
- pattern: a regex over the counterparty names and the remittance text,
  case-insensitive (categorization_rules.search_text);
- when: a condition (finance_core.rule_conditions), `-` for none;
- category: a category of the direction's block, or `ai`: stop here and
  leave the row to the AI;
- mark: `?` writes the category marked for the user to check, `-` plain;
- description: what the sheet shows, `-` only on an `ai` line;
- source: where the line came from (the draft's group id), not read.

The rules run after the tables in constants.py, first match wins. A bad
line stops the whole file with its line number and what is wrong, never its
text, so a typo cannot quietly change what the bot writes.
"""

import os
import re
from typing import List, NamedTuple, Optional

from constants import ExpenseCategory, IncomeCategory
from finance_core.config_access import project_path, setting
from finance_core.rule_conditions import parse_when

DEFAULT_PATH = "src/config/local_rules.tsv"
AI = "ai"


class LocalRulesError(ValueError):
    """The local rules file has a line the bot cannot use."""


class LocalRule(NamedTuple):
    line: int
    direction: str
    pattern: str
    regex: re.Pattern
    when: object
    category: Optional[object]      # None on an `ai` line
    marked: bool
    description: Optional[str]


def _category(name, direction):
    enum = IncomeCategory if direction == "in" else ExpenseCategory
    for member in enum:
        if member.value == name:
            return member
    raise ValueError(f"not a category of the {'income' if direction == 'in' else 'expense'} block")


def _rule(n, fields):
    if len(fields) < 6:
        raise ValueError("expected 6 columns (direction, pattern, when, category, mark, description)")
    direction, pattern, when, category, mark, description = (f.strip() for f in fields[:6])
    if direction not in ("in", "out"):
        raise ValueError("direction must be `in` or `out`")
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error:
        raise ValueError("the pattern is not a valid regex") from None
    try:
        predicate = parse_when(when)
    except ValueError as exc:
        raise ValueError(f"the condition is not valid ({exc})") from None
    if category == AI:
        return LocalRule(n, direction, pattern, regex, predicate, None, False, None)
    try:
        member = _category(category, direction)
    except ValueError as exc:
        raise ValueError(f"the category is {exc}") from None
    if mark not in ("?", "-"):
        raise ValueError("the mark must be `?` or `-`")
    if description in ("", "-"):
        raise ValueError("a rule with a category needs a description")
    return LocalRule(n, direction, pattern, regex, predicate, member, mark == "?", description)


def parse_local_rules(text, name="local_rules.tsv") -> List[LocalRule]:
    rules = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            rules.append(_rule(n, line.split("\t")))
        except ValueError as exc:
            raise LocalRulesError(f"{name} line {n}: {exc}") from None
    return rules


def load_local_rules(path) -> List[LocalRule]:
    """The rules in `path`; none when the file does not exist."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return []
    return parse_local_rules(text, os.path.basename(os.fspath(path)))


_cache = {}


def default_local_rules() -> List[LocalRule]:
    """The configured file's rules, read again when the file changes."""
    path = project_path(setting("LOCAL_RULES_PATH", DEFAULT_PATH))
    try:
        st = os.stat(path)
        key = (path, st.st_mtime_ns, st.st_size)
    except FileNotFoundError:
        key = (path, None, None)
    if key not in _cache:
        _cache.clear()
        _cache[key] = load_local_rules(path)
    return _cache[key]
