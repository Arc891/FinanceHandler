"""
Hosted Jev through OpenRouter, for the shadow-eval's control arm
(jev-investigation.md §5.1 step 1, arm 2).

Every request is pinned to `typesafe/jev-1.13`, served by TypeSafe only,
with zero data retention required and no fallback to another provider. A
run checks OpenRouter's public ZDR list first and stops on a changed model
in any answer. Plain HTTPS through `requests`; no SDK.

Errors carry the HTTP status only, never a response body: a body may echo
the request, and the request holds (anonymised) transaction text.
"""

import re
import time

API = "https://openrouter.ai/api/v1"
MODEL = "typesafe/jev-1.13"
PROVIDER = {"zdr": True, "only": ["typesafe"], "allow_fallbacks": False, "data_collection": "deny"}
OTHER = "other"
RETRY_DELAYS = (2, 5, 15, 30)
TIMEOUT = 30

NOULS = {
    "transfer": ("Is this a transfer between the household's own accounts, such as to or from "
                 "a savings account or a partner's account?"),
    "refund": "Is this a refund or reversal of an earlier payment?",
    "recurring": "Is this a recurring payment such as a subscription, a bill, rent or a salary?",
}


class JevError(Exception):
    """A failed decision; the message names the status, never row content."""


class ModelChanged(JevError):
    """An answer came from a model other than the pinned one."""


def new_session():
    import requests
    return requests.Session()


# ── questions ───────────────────────────────────────────────────────────────

def _readable(pattern) -> str:
    s = re.sub(r"\(\?[a-z]+\)", "", pattern)
    s = re.sub(r"\\[bBdDsSwW]", " ", s)
    s = re.sub(r"[\\^$()\[\]{}*+?.]", "", s)
    return " ".join(s.replace("|", ", ").split()).strip(" ,")


def category_descriptions(categories, example_rules):
    """{category: description}: the category's name, plus the bank texts of
    the example rules Sonnet's prompt shows for it."""
    examples = {}
    for pattern, (_, category) in example_rules.items():
        examples.setdefault(category, []).append(_readable(pattern))
    out = {}
    for c in categories:
        ex = [e for e in examples.get(c, []) if e]
        out[c] = f"{c} (bank texts such as: {'; '.join(ex[:6])})" if ex else c
    return out


def questions(category_criteria):
    """The question set for one block: the category, with an explicit other,
    and three yes/no signals recorded beside it."""
    criteria = {**category_criteria, OTHER: "none of the categories above fits"}
    qs = {"category": {
        "type": "choice",
        "instructions": ("Which budget category does `transaction` belong to in this Dutch "
                         "household's monthly budget? `same_counterparty_this_month` lists "
                         "already-categorised rows of the same counterparty."),
        "criteria": criteria}}
    for qid, text in NOULS.items():
        qs[qid] = {"type": "noul", "instructions": text}
    return qs


# ── calls ───────────────────────────────────────────────────────────────────

def zdr_ok(session) -> bool:
    """Whether OpenRouter's public zero-data-retention list holds Jev 1.13 at TypeSafe."""
    try:
        resp = session.get(f"{API}/endpoints/zdr", timeout=TIMEOUT)
        if resp.status_code != 200:
            return False
        rows = resp.json().get("data", [])
    except Exception:                       # noqa: BLE001 - any failure means not confirmed
        return False
    return any(r.get("model_id") == MODEL and str(r.get("provider_name", "")).lower() == "typesafe"
               for r in rows if isinstance(r, dict))


def _pinned(model) -> bool:
    return model == MODEL or str(model).startswith(MODEL + "-")


def decide(session, key, state, qs, sleep=time.sleep):
    """{"category" (None for other), "confidence" (top probability),
    "nouls", "model"} for one state."""
    body = {"model": MODEL, "state": state, "questions": qs, "provider": PROVIDER}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    for attempt in range(len(RETRY_DELAYS) + 1):
        resp = session.post(f"{API}/systemone", json=body, headers=headers, timeout=TIMEOUT)
        status = resp.status_code
        if status == 200:
            break
        if (status == 429 or status >= 500) and attempt < len(RETRY_DELAYS):
            try:
                wait = float(resp.headers.get("Retry-After", RETRY_DELAYS[attempt]))
            except (TypeError, ValueError):
                wait = float(RETRY_DELAYS[attempt])
            sleep(wait)
            continue
        raise JevError(f"Jev request failed (HTTP {status})")
    data = resp.json()
    if not _pinned(data.get("model")):
        raise ModelChanged("Jev answered with a model other than jev-1.13; run stopped")
    if str(data.get("provider", "")).lower() != "typesafe":
        raise JevError("Jev answered through a provider other than TypeSafe; run stopped")
    answers = data.get("answers") or {}
    cat = answers.get("category") or {}
    probs = cat.get("probabilities") or {}
    choice = cat.get("choice")
    confidence = float(probs.get(choice, max(probs.values(), default=0.0)))
    nouls = {q: float(answers[q]["noul"]) for q in NOULS if isinstance(answers.get(q), dict)
             and "noul" in answers[q]}
    return {"category": None if choice in (None, OTHER) else choice, "confidence": confidence,
            "nouls": nouls, "model": data.get("model")}
