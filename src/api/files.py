"""File serving API endpoint.

Serves generated files (charts, maps, PDFs) from the data directory.
"""

import logging
import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/files", tags=["files"])

# Base data directory
DATA_DIR = Path("data")


@router.get("/{file_id}")
async def serve_file(file_id: str):
    """Serve a generated file (chart, map, PDF, CSV).

    Files are stored in the data/ directory. The file_id can be:
    - A simple filename (e.g., "chart_123.png")
    - A session-scoped path (e.g., "outputs/session_id/chart.png")
    - A UUID-based filename

    Supported file types:
    - PNG images (charts)
    - HTML files
    - PDF files (reports)
    - CSV files (data exports)
    """
    # Security: prevent directory traversal
    if ".." in file_id or file_id.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid file_id")

    # Try to find the file in various locations
    possible_paths = [
        DATA_DIR / file_id,  # Direct path
        DATA_DIR / "outputs" / file_id,  # In outputs directory
    ]

    # Also check for session-specific outputs
    if "/" not in file_id:
        # If it's just a filename, search in all session directories
        outputs_dir = DATA_DIR / "outputs"
        if outputs_dir.exists():
            for session_dir in outputs_dir.iterdir():
                if session_dir.is_dir():
                    possible_paths.append(session_dir / file_id)

    # Find the first existing file
    file_path = None
    for path in possible_paths:
        if path.exists() and path.is_file():
            file_path = path
            break

    if not file_path:
        logger.warning(f"File not found: {file_id}")
        raise HTTPException(status_code=404, detail=f"File not found: {file_id}")

    # Determine media type
    media_type = mimetypes.guess_type(str(file_path))[0]

    # Override for common types
    suffix = file_path.suffix.lower()
    if suffix == ".png":
        media_type = "image/png"
    elif suffix == ".jpg" or suffix == ".jpeg":
        media_type = "image/jpeg"
    elif suffix == ".html":
        media_type = "text/html"
    elif suffix == ".pdf":
        media_type = "application/pdf"
    elif suffix == ".csv":
        media_type = "text/csv"
    elif suffix == ".json":
        media_type = "application/json"
    else:
        media_type = media_type or "application/octet-stream"

    logger.info(f"Serving file: {file_path} as {media_type}")

    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=file_path.name,
    )
