"""
MADMIN File Upload Router

Handles file uploads for logos, favicons, and other static assets.
Files are stored in /opt/madmin/uploads/ and served via Nginx.
"""
import os
import uuid
import aiofiles
from typing import List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse

from core.auth.dependencies import require_permission, get_current_user
from core.auth.models import User

router = APIRouter(prefix="/api/files", tags=["Files"])

# Upload directory configuration
UPLOAD_DIR = os.environ.get("MADMIN_UPLOAD_DIR", "/opt/madmin/uploads")
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp"}
MAX_FILE_SIZE = 2 * 1024 * 1024  # 2MB


def get_upload_dir():
    """Ensure upload directory exists and return path."""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    return UPLOAD_DIR


def validate_file(file: UploadFile) -> None:
    """Validate uploaded file type and size."""
    # Check extension
    _, ext = os.path.splitext(file.filename or "")
    if ext.lower() not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    current_user: User = Depends(require_permission("settings.manage"))
):
    """
    Upload a file (logo, favicon, etc.)
    Returns the URL to access the uploaded file.
    """
    validate_file(file)
    
    # Check file size
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size: {MAX_FILE_SIZE // (1024*1024)}MB"
        )
    
    # Generate unique filename
    _, ext = os.path.splitext(file.filename or "file")
    unique_name = f"{uuid.uuid4().hex}{ext.lower()}"
    
    # Save file
    upload_dir = get_upload_dir()
    file_path = os.path.join(upload_dir, unique_name)
    
    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)
    
    # Return URL (Nginx will serve /uploads/ from UPLOAD_DIR)
    file_url = f"/uploads/{unique_name}"
    
    return {
        "url": file_url,
        "filename": unique_name,
        "original_name": file.filename,
        "size": len(content)
    }


@router.delete("/upload/{filename}")
async def delete_file(
    filename: str,
    current_user: User = Depends(require_permission("settings.manage"))
):
    """Delete an uploaded file."""
    # Sanitize filename (prevent directory traversal)
    safe_name = os.path.basename(filename)
    file_path = os.path.join(get_upload_dir(), safe_name)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    os.remove(file_path)
    return {"status": "ok", "message": "File deleted"}
