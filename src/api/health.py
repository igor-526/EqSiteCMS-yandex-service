"""Health check endpoint."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from utils.database import get_engine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check():
    """
    Health check endpoint with database connectivity check.
    
    Access: Public Read (no authentication required)
    
    Returns:
        200 OK: Service is healthy
        503 Service Unavailable: Service is unhealthy (database unavailable)
    """
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    
    try:
        # Check database connection
        engine = get_engine()
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        
        return {
            "status": "healthy",
            "timestamp": timestamp,
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "error": str(e),
                "timestamp": timestamp,
            },
        )
