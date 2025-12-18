# finance_core/pending_transactions.py
"""
Manages the queue of low-confidence transactions awaiting Discord approval.
Transactions are stored persistently and can be approved/rejected via Discord buttons.
"""

import json
import os
import uuid
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger(__name__)


def _get_pending_file_path() -> str:
    """Get the path to the pending approvals file."""
    try:
        from config.config_settings import PENDING_APPROVALS_FILE
        # Resolve relative to project root
        base_dir = os.path.dirname(
            os.path.dirname(
                os.path.dirname(
                    os.path.abspath(__file__))))
        return os.path.join(base_dir, PENDING_APPROVALS_FILE)
    except ImportError:
        base_dir = os.path.dirname(
            os.path.dirname(
                os.path.dirname(
                    os.path.abspath(__file__))))
        return os.path.join(base_dir, "data", "pending_approvals.json")


def load_pending_queue() -> Dict[str, Any]:
    """Load the pending approvals queue from disk."""
    file_path = _get_pending_file_path()
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error loading pending queue: {e}")
            return {"pending": {}, "processed": []}
    return {"pending": {}, "processed": []}


def _save_pending_queue(queue: Dict[str, Any]) -> None:
    """Save the pending approvals queue to disk."""
    file_path = _get_pending_file_path()
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    try:
        with open(file_path, 'w') as f:
            json.dump(queue, f, indent=2, default=str)
    except IOError as e:
        logger.error(f"Error saving pending queue: {e}")


def add_pending_transaction(
    user_id: int,
    transaction: Dict[str, Any],
    ai_category: Optional[str],
    ai_description: Optional[str],
    ai_confidence: float,
    transaction_type: str
) -> str:
    """
    Add a transaction to the pending approval queue.

    Args:
        user_id: Discord user ID who uploaded the transaction
        transaction: The raw transaction data
        ai_category: AI's suggested category (or None)
        ai_description: AI's suggested description (or None)
        ai_confidence: AI's confidence score (0.0-1.0)
        transaction_type: "income" or "expense"

    Returns:
        approval_id: Unique ID for this pending approval
    """
    queue = load_pending_queue()

    approval_id = str(uuid.uuid4())[:8]  # Short UUID for display

    pending_item = {
        "approval_id": approval_id,
        "user_id": user_id,
        "transaction": transaction,
        "ai_category": ai_category,
        "ai_description": ai_description,
        "ai_confidence": ai_confidence,
        "transaction_type": transaction_type,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
        "message_id": None,  # Will be set when Discord message is sent
        "thread_id": None    # Will be set when private thread is created
    }

    queue["pending"][approval_id] = pending_item
    _save_pending_queue(queue)

    logger.info(f"Added pending transaction {approval_id} for user {user_id}")
    return approval_id


def set_message_id(approval_id: str, message_id: int) -> bool:
    """
    Link a Discord message ID to a pending approval.

    Args:
        approval_id: The approval ID
        message_id: Discord message ID

    Returns:
        True if successful, False if approval not found
    """
    queue = load_pending_queue()

    if approval_id not in queue["pending"]:
        logger.warning(
            f"Approval {approval_id} not found when setting message_id")
        return False

    queue["pending"][approval_id]["message_id"] = message_id
    _save_pending_queue(queue)
    return True


def set_thread_id(approval_id: str, thread_id: int) -> bool:
    """
    Link a Discord thread ID to a pending approval.

    Args:
        approval_id: The approval ID
        thread_id: Discord thread ID

    Returns:
        True if successful, False if approval not found
    """
    queue = load_pending_queue()

    if approval_id not in queue["pending"]:
        logger.warning(
            f"Approval {approval_id} not found when setting thread_id")
        return False

    queue["pending"][approval_id]["thread_id"] = thread_id
    _save_pending_queue(queue)
    return True


def get_pending_by_message_id(message_id: int) -> Optional[Dict[str, Any]]:
    """
    Find a pending approval by its Discord message ID.

    Args:
        message_id: Discord message ID

    Returns:
        Pending item dict or None if not found
    """
    queue = load_pending_queue()

    for approval_id, item in queue["pending"].items():
        if item.get("message_id") == message_id:
            return item

    return None


def get_pending_by_id(approval_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a pending approval by its ID.

    Args:
        approval_id: The approval ID

    Returns:
        Pending item dict or None if not found
    """
    queue = load_pending_queue()
    return queue["pending"].get(approval_id)


def get_user_pending_transactions(user_id: int) -> List[Dict[str, Any]]:
    """
    Get all pending transactions for a specific user.

    Args:
        user_id: Discord user ID

    Returns:
        List of pending transaction dicts
    """
    queue = load_pending_queue()
    return [
        item for item in queue["pending"].values()
        if item["user_id"] == user_id and item["status"] == "pending"
    ]


def approve_transaction(
    approval_id: str,
    final_category: str,
    final_description: str,
    approved_by: int
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Approve a pending transaction with final category and description.

    Args:
        approval_id: The approval ID
        final_category: The approved category
        final_description: The approved description
        approved_by: Discord user ID who approved

    Returns:
        Tuple of (success, transaction_data for upload)
    """
    queue = load_pending_queue()

    if approval_id not in queue["pending"]:
        logger.warning(f"Approval {approval_id} not found")
        return False, None

    item = queue["pending"][approval_id]

    # Prepare transaction for upload
    transaction = item["transaction"].copy()
    transaction["category"] = final_category
    transaction["description"] = final_description

    # Store result data before deleting
    result_data = {
        "transaction": transaction,
        "transaction_type": item["transaction_type"],
        "user_id": item["user_id"],
        "message_id": item.get("message_id"),
        "thread_id": item.get("thread_id")
    }

    # Simply delete - no need to keep processed forever
    del queue["pending"][approval_id]
    _save_pending_queue(queue)

    logger.info(f"Approved transaction {approval_id} as {final_category}")
    return True, result_data


def reject_transaction(
        approval_id: str, rejected_by: int) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Reject/skip a pending transaction (discard it).

    Args:
        approval_id: The approval ID
        rejected_by: Discord user ID who rejected

    Returns:
        Tuple of (success, info dict with message_id/thread_id for cleanup)
    """
    queue = load_pending_queue()

    if approval_id not in queue["pending"]:
        logger.warning(f"Approval {approval_id} not found")
        return False, None

    item = queue["pending"][approval_id]

    # Store IDs for potential message cleanup
    result_info = {
        "message_id": item.get("message_id"),
        "thread_id": item.get("thread_id"),
        "user_id": item["user_id"]
    }

    # Simply delete - no need to keep rejected items
    del queue["pending"][approval_id]
    _save_pending_queue(queue)

    logger.info(f"Rejected/skipped transaction {approval_id}")
    return True, result_info


def get_pending_count(user_id: Optional[int] = None) -> int:
    """
    Get count of pending approvals.

    Args:
        user_id: If provided, count only for this user

    Returns:
        Number of pending approvals
    """
    queue = load_pending_queue()

    if user_id is None:
        return len(queue["pending"])

    return sum(
        1 for item in queue["pending"].values()
        if item["user_id"] == user_id and item["status"] == "pending"
    )


def clear_user_pending(user_id: int) -> int:
    """
    Clear all pending approvals for a user.

    Args:
        user_id: Discord user ID

    Returns:
        Number of items cleared
    """
    queue = load_pending_queue()

    to_remove = [
        aid for aid, item in queue["pending"].items()
        if item["user_id"] == user_id
    ]

    for aid in to_remove:
        del queue["pending"][aid]

    _save_pending_queue(queue)
    logger.info(
        f"Cleared {len(to_remove)} pending approvals for user {user_id}")
    return len(to_remove)


def cleanup_processed_list() -> int:
    """
    Remove old entries from the processed list (if any exist from before cleanup change).

    Returns:
        Number of entries removed
    """
    queue = load_pending_queue()

    old_count = len(queue.get("processed", []))
    queue["processed"] = []  # Clear all processed
    _save_pending_queue(queue)

    if old_count > 0:
        logger.info(f"Cleaned up {old_count} old processed entries")
    return old_count
