"""
FastAPI endpoints for n8n automation integration.

Provides HTTP API for:
- Bank transaction downloads
- QR login initiation
- Transaction processing
- Approval handling
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Header, Body
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

# Will be implemented in later sessions
# from automation.automation_orchestrator import AutomationOrchestrator

logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Finance Automation API",
    description="API endpoints for n8n to trigger finance automation workflows",
    version="1.0.0"
)


# Request/Response Models
class DateRangeRequest(BaseModel):
    date_from: Optional[str] = None  # DD-MM-YYYY format
    date_to: Optional[str] = None    # DD-MM-YYYY format
    days_back: Optional[int] = 7     # Default to last 7 days


class QRLoginResponse(BaseModel):
    success: bool
    qr_image_path: Optional[str] = None
    message: str


class DownloadResponse(BaseModel):
    success: bool
    csv_path: Optional[str] = None
    message: str
    transaction_count: Optional[int] = None


class SessionCheckResponse(BaseModel):
    valid: bool
    message: str


class TransactionApproval(BaseModel):
    approval_id: str
    category: str
    description: str


# Authentication
def verify_api_key(x_api_key: str = Header(None)) -> bool:
    """Verify API key from header."""
    try:
        from config_settings import API_SECRET_KEY
        expected_key = API_SECRET_KEY
    except ImportError:
        expected_key = os.environ.get('API_SECRET_KEY', 'change-me-in-production')

    if not x_api_key or x_api_key != expected_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return True


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "running",
        "service": "Finance Automation API",
        "version": "1.0.0"
    }


@app.get("/health")
async def health_check():
    """Detailed health check."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "components": {
            "api": "running",
            "bank_scraper": "available",
            "ai_categorizer": "pending_implementation"
        }
    }


@app.post("/api/qr-login", response_model=QRLoginResponse)
async def initiate_qr_login(x_api_key: str = Header(..., alias="X-API-Key")):
    """
    Initiate QR login flow for ASN Bank.

    Returns QR code image path for Discord to upload.
    """
    verify_api_key(x_api_key)

    try:
        from automation.bank_scraper import ASNBankScraper

        scraper = ASNBankScraper()
        success, qr_path = await scraper.login_with_qr()
        await scraper.cleanup()

        if success:
            return QRLoginResponse(
                success=True,
                qr_image_path=qr_path,
                message="QR login successful, session saved"
            )
        else:
            return QRLoginResponse(
                success=False,
                message=f"QR login failed: {qr_path}"
            )

    except Exception as e:
        logger.error(f"❌ QR login endpoint error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/check-session", response_model=SessionCheckResponse)
async def check_bank_session(x_api_key: str = Header(..., alias="X-API-Key")):
    """
    Check if bank session is still valid.

    Returns:
        SessionCheckResponse with validity status
    """
    verify_api_key(x_api_key)

    try:
        from automation.bank_scraper import ASNBankScraper

        scraper = ASNBankScraper()
        is_valid = await scraper.is_session_valid()
        await scraper.cleanup()

        if is_valid:
            return SessionCheckResponse(
                valid=True,
                message="Bank session is valid"
            )
        else:
            return SessionCheckResponse(
                valid=False,
                message="Bank session expired, QR login required"
            )

    except Exception as e:
        logger.error(f"❌ Session check endpoint error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/download-transactions", response_model=DownloadResponse)
async def download_transactions(
    date_range: DateRangeRequest = Body(...),
    x_api_key: str = Header(..., alias="X-API-Key")
):
    """
    Download transactions from ASN Bank as CSV.

    Args:
        date_range: Date range specification (either explicit dates or days_back)

    Returns:
        DownloadResponse with CSV path and transaction count
    """
    verify_api_key(x_api_key)

    try:
        from automation.bank_scraper import ASNBankScraper

        # Calculate date range
        if date_range.date_from and date_range.date_to:
            date_from = date_range.date_from
            date_to = date_range.date_to
        else:
            # Use days_back
            today = datetime.now()
            date_to = today.strftime("%d-%m-%Y")
            past_date = today - timedelta(days=date_range.days_back)
            date_from = past_date.strftime("%d-%m-%Y")

        logger.info(f"📥 Download request: {date_from} to {date_to}")

        # Download CSV
        scraper = ASNBankScraper()
        csv_path = await scraper.download_transactions(date_from, date_to)
        await scraper.cleanup()

        if csv_path:
            # Count transactions in CSV (optional)
            try:
                with open(csv_path, 'r', encoding='utf-8') as f:
                    line_count = sum(1 for line in f) - 1  # Subtract header
                transaction_count = max(0, line_count)
            except:
                transaction_count = None

            return DownloadResponse(
                success=True,
                csv_path=csv_path,
                message=f"Downloaded {transaction_count or 'unknown'} transactions",
                transaction_count=transaction_count
            )
        else:
            return DownloadResponse(
                success=False,
                message="Download failed, check logs for details"
            )

    except Exception as e:
        logger.error(f"❌ Download endpoint error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/process-batch")
async def process_transaction_batch(
    csv_path: str = Body(..., embed=True),
    x_api_key: str = Header(..., alias="X-API-Key")
):
    """
    Process a batch of transactions from CSV.

    This will be implemented in Session 4 when we build the orchestrator.

    Args:
        csv_path: Path to CSV file to process

    Returns:
        Processing results
    """
    verify_api_key(x_api_key)

    # Placeholder for Session 4 implementation
    return JSONResponse(
        status_code=501,
        content={
            "status": "not_implemented",
            "message": "Transaction processing will be implemented in Session 4",
            "csv_path": csv_path
        }
    )


@app.post("/api/approve-transaction")
async def approve_transaction(
    approval: TransactionApproval = Body(...),
    x_api_key: str = Header(..., alias="X-API-Key")
):
    """
    Handle transaction approval from Discord.

    This will be implemented in Session 3 when we build the approval UI.

    Args:
        approval: Approval details (ID, category, description)

    Returns:
        Approval processing result
    """
    verify_api_key(x_api_key)

    # Placeholder for Session 3 implementation
    return JSONResponse(
        status_code=501,
        content={
            "status": "not_implemented",
            "message": "Approval handling will be implemented in Session 3",
            "approval_id": approval.approval_id
        }
    )


@app.get("/api/qr-image/{filename}")
async def get_qr_image(
    filename: str,
    x_api_key: str = Header(..., alias="X-API-Key")
):
    """
    Serve QR code image for download.

    Args:
        filename: QR image filename

    Returns:
        QR code image file
    """
    verify_api_key(x_api_key)

    file_path = f"/tmp/{filename}"
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="QR image not found")

    return FileResponse(file_path, media_type="image/png")


# Error handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Handle HTTP exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail}
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Handle general exceptions."""
    logger.error(f"❌ Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)}
    )


# Run server
if __name__ == "__main__":
    import uvicorn

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Get port from environment or config
    try:
        from config_settings import API_PORT, API_HOST
        port = API_PORT
        host = API_HOST
    except ImportError:
        port = 8000
        host = "0.0.0.0"

    logger.info(f"🚀 Starting Finance Automation API on {host}:{port}")

    uvicorn.run(app, host=host, port=port)
