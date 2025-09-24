#!/usr/bin/env python3
"""
Script to retry failed transactions that couldn't be uploaded due to sheet size limits.
Use this when you have categorized transactions in your session that failed to upload.
"""

import sys
import os
import logging

# Add the src directory to Python path so we can import modules
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))

from finance_core.background_upload import (
    start_upload_queue, 
    retry_failed_transactions, 
    clear_failed_transactions_after_retry,
    get_upload_queue
)
from finance_core.session_management import load_session
import time

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    if len(sys.argv) != 2:
        print("Usage: python retry_failed_transactions.py <user_id>")
        print("Example: python retry_failed_transactions.py 1395443068227948630")
        sys.exit(1)
    
    try:
        user_id = int(sys.argv[1])
    except ValueError:
        print("Error: user_id must be a valid integer")
        sys.exit(1)
    
    logger.info(f"🔄 Starting retry process for user {user_id}")
    
    try:
        # First, check what failed transactions exist
        remaining, income_transactions, expense_transactions = load_session(user_id)
        
        failed_count = len(income_transactions) + len(expense_transactions)
        if failed_count == 0:
            logger.info("ℹ️ No failed transactions found in session. Nothing to retry.")
            return
        
        logger.info(f"📊 Found {len(expense_transactions)} failed expense transactions and {len(income_transactions)} failed income transactions")
        
        # Show a few examples of what will be retried
        if expense_transactions:
            logger.info("📝 Example failed expense transactions:")
            for i, tx in enumerate(expense_transactions[:3]):
                desc = tx.get('description', tx.get('remittance_information', ['Unknown'])[:1])
                amount = tx.get('transaction_amount', {}).get('amount', 'Unknown')
                category = tx.get('category', 'No category')
                logger.info(f"  {i+1}. {desc} - €{amount} - {category}")
            if len(expense_transactions) > 3:
                logger.info(f"  ... and {len(expense_transactions) - 3} more")
        
        if income_transactions:
            logger.info("📝 Example failed income transactions:")
            for i, tx in enumerate(income_transactions[:3]):
                desc = tx.get('description', tx.get('remittance_information', ['Unknown'])[:1])
                amount = tx.get('transaction_amount', {}).get('amount', 'Unknown')
                category = tx.get('category', 'No category')
                logger.info(f"  {i+1}. {desc} - €{amount} - {category}")
            if len(income_transactions) > 3:
                logger.info(f"  ... and {len(income_transactions) - 3} more")
        
        # Start the upload queue
        logger.info("🚀 Starting upload queue...")
        start_upload_queue()
        
        # Wait a moment for queue to initialize
        time.sleep(1)
        
        # Retry the failed transactions
        logger.info("🔄 Queueing failed transactions for retry...")
        retry_count = retry_failed_transactions(user_id)
        
        if retry_count == 0:
            logger.warning("⚠️ No transactions were queued for retry. They may lack required fields like category.")
            return
        
        logger.info(f"✅ Successfully queued {retry_count} transactions for retry")
        logger.info("⏳ Waiting for uploads to complete...")
        
        # Wait for the queue to process all transactions
        # Monitor the queue size to see when it's done
        queue = get_upload_queue()
        max_wait_time = 300  # 5 minutes max
        wait_time = 0
        
        while wait_time < max_wait_time:
            queue_size = queue.upload_queue.qsize()
            if queue_size == 0:
                logger.info("✅ All transactions have been processed!")
                break
            
            logger.info(f"⏳ {queue_size} transactions remaining in queue...")
            time.sleep(10)
            wait_time += 10
        
        if wait_time >= max_wait_time:
            logger.warning("⚠️ Timed out waiting for uploads to complete. Check logs for any errors.")
        else:
            # Clear the failed transactions from session since they should now be uploaded
            logger.info("🧹 Clearing retried transactions from session...")
            clear_failed_transactions_after_retry(user_id)
            logger.info("✅ Retry process completed successfully!")
    
    except Exception as e:
        logger.error(f"❌ Error during retry process: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()