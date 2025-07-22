# finance_core/session_management.py

import os
import json
import uuid
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime

# Import session directory from config
try:
    from config_settings import SESSION_DIR as _SESSION_DIR
    # Make the session directory absolute relative to the project root
    # This file is at: finance_core/session_management.py
    # Go up: finance_core -> src -> project_root (two levels up)
    _this_file = os.path.abspath(__file__)
    _src_dir = os.path.dirname(os.path.dirname(_this_file))
    _project_root = os.path.dirname(_src_dir)
    SESSION_DIR = os.path.join(_project_root, _SESSION_DIR)
except ImportError:
    # Fallback: use absolute path from current file location
    _this_file = os.path.abspath(__file__)
    _src_dir = os.path.dirname(os.path.dirname(_this_file))
    _project_root = os.path.dirname(_src_dir)
    SESSION_DIR = os.path.join(_project_root, "data/sessions")

os.makedirs(SESSION_DIR, exist_ok=True)

def get_session_path(user_id: int) -> str:
    return os.path.join(SESSION_DIR, f"{user_id}.json")

def _load_full_session(user_id: int) -> Dict[str, Any]:
    """Load the complete session data structure"""
    path = get_session_path(user_id)
    if not os.path.exists(path):
        return {
            "remaining": [],
            "income": [],
            "expenses": [],
            "cached": [],
            "sheet_positions": {
                "expense_row": 2,
                "income_row": 2,
                "last_updated": None
            }
        }

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
        # Ensure all required fields exist with defaults
        return {
            "remaining": data.get("remaining", []),
            "income": data.get("income", []),
            "expenses": data.get("expenses", []),
            "cached": data.get("cached", []),
            "sheet_positions": data.get("sheet_positions", {
                "expense_row": 2,
                "income_row": 2,
                "last_updated": None
            })
        }

def _save_full_session(user_id: int, session_data: Dict[str, Any]) -> None:
    """Save the complete session data structure"""
    with open(get_session_path(user_id), "w", encoding="utf-8") as f:
        json.dump(session_data, f, indent=2)

def save_session(user_id: int, remaining: List[Dict[str, Any]], income: List[Dict[str, Any]], expenses: List[Dict[str, Any]]) -> None:
    session_data = _load_full_session(user_id)
    session_data.update({
        "remaining": remaining,
        "income": income,
        "expenses": expenses
    })
    _save_full_session(user_id, session_data)

def load_session(user_id: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    session_data = _load_full_session(user_id)
    return (
        session_data["remaining"],
        session_data["income"],
        session_data["expenses"]
    )

def session_exists(user_id: int) -> bool:
    return os.path.exists(get_session_path(user_id))

def clear_session(user_id: int) -> None:
    path = get_session_path(user_id)
    if os.path.exists(path):
        os.remove(path)

# === Cached Transactions Management ===

def cache_transaction(user_id: int, transaction: Dict[str, Any], transaction_type: str, auto_description: str) -> str:
    """Cache a transaction with auto-generated description and dummy category"""
    session_data = _load_full_session(user_id)
    
    cache_id = str(uuid.uuid4())[:8]  # Short UUID
    
    cached_transaction = {
        "cache_id": cache_id,
        "original_transaction": transaction,
        "amount": transaction.get("transaction_amount", {}).get("amount", "0"),
        "auto_description": auto_description,
        "transaction_type": transaction_type,
        "timestamp": datetime.now().isoformat(),
        "sheet_row": None  # Will be set when uploaded to sheet
    }
    
    session_data["cached"].append(cached_transaction)
    _save_full_session(user_id, session_data)
    
    return cache_id

def get_cached_transactions(user_id: int) -> List[Dict[str, Any]]:
    """Get all cached transactions for a user"""
    session_data = _load_full_session(user_id)
    return session_data["cached"]

def remove_cached_transaction(user_id: int, cache_id: str) -> bool:
    """Remove a cached transaction by cache_id"""
    session_data = _load_full_session(user_id)
    
    for i, cached_tx in enumerate(session_data["cached"]):
        if cached_tx["cache_id"] == cache_id:
            del session_data["cached"][i]
            _save_full_session(user_id, session_data)
            return True
    
    return False

def update_cached_transaction_row(user_id: int, cache_id: str, sheet_row: int) -> bool:
    """Update the sheet row for a cached transaction"""
    session_data = _load_full_session(user_id)
    
    for cached_tx in session_data["cached"]:
        if cached_tx["cache_id"] == cache_id:
            cached_tx["sheet_row"] = sheet_row
            _save_full_session(user_id, session_data)
            return True
    
    return False

def clear_cached_transactions(user_id: int) -> None:
    """Clear all cached transactions for a user"""
    session_data = _load_full_session(user_id)
    session_data["cached"] = []
    _save_full_session(user_id, session_data)

# === Sheet Positions Management ===

def get_sheet_positions(user_id: int) -> Dict[str, Any]:
    """Get sheet positions for a user"""
    session_data = _load_full_session(user_id)
    return session_data["sheet_positions"]

def save_sheet_positions(user_id: int, expense_row: int, income_row: int) -> None:
    """Save sheet positions for a user"""
    session_data = _load_full_session(user_id)
    session_data["sheet_positions"] = {
        "expense_row": expense_row,
        "income_row": income_row,
        "last_updated": datetime.now().isoformat()
    }
    _save_full_session(user_id, session_data)

def reset_sheet_positions(user_id: int) -> None:
    """Reset sheet positions to defaults"""
    session_data = _load_full_session(user_id)
    session_data["sheet_positions"] = {
        "expense_row": 2,
        "income_row": 2,
        "last_updated": None
    }
    _save_full_session(user_id, session_data)
