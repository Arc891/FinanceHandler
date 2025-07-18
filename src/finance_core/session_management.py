# finance_core/session_management.py

import os
import json
from typing import List, Dict, Any, Tuple

SESSION_DIR = "sessions"
os.makedirs(SESSION_DIR, exist_ok=True)

def get_session_path(user_id: int) -> str:
    return os.path.join(SESSION_DIR, f"{user_id}.json")

def save_session(user_id: int, remaining: List[Dict[str, Any]], income: List[Dict[str, Any]], expenses: List[Dict[str, Any]]) -> None:
    data = {
        "remaining": remaining,
        "income": income,
        "expenses": expenses
    }
    with open(get_session_path(user_id), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def load_session(user_id: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    path = get_session_path(user_id)
    if not os.path.exists(path):
        return [], [], []

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
        return (
            data.get("remaining") or [],
            data.get("income") or [],
            data.get("expenses") or []
        )

def session_exists(user_id: int) -> bool:
    return os.path.exists(get_session_path(user_id))

def clear_session(user_id: int) -> None:
    path = get_session_path(user_id)
    if os.path.exists(path):
        os.remove(path)
