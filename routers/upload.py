"""
routers/upload.py
POST /api/ai/upload — accepts a PDF/Excel/CSV file, validates it, and saves
the original to Azure Blob Storage (container: eln-chat-uploads).

Parsing (PDF text extraction, Excel/CSV summarization) is NOT implemented
yet — this increment covers validation + blob save + stub response only.
"""

import uuid
import os
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
from azure.identity import ManagedIdentityCredential
from azure.storage.blob import BlobServiceClient

router = APIRouter()

STORAGE_ACCOUNT_NAME = "stelncoovalent"
UPLOAD_CONTAINER_NAME = "eln-chat-uploads"
ALLOWED_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".csv"}
MAX_FILE_SIZE_BYTES = 15 * 1024 * 1024  # 15MB


class UploadResponse(BaseModel):
    file_id: str
    filename: str
    size_bytes: int
    summary: str
    truncated: bool


def _get_blob_service_client() -> BlobServiceClient:
    account_url = f"https://{STORAGE_ACCOUNT_NAME}.blob.core.windows.net"
    credential = ManagedIdentityCredential()
    return BlobServiceClient(account_url=account_url, credential=credential)


@router.post("/api/ai/upload", response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...)):
    original_filename = file.filename or "unnamed"
    _, ext = os.path.splitext(original_filename.lower())

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}",
        )

    file_bytes = await file.read()
    size_bytes = len(file_bytes)

    if size_bytes > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File too large ({size_bytes} bytes). Max allowed is {MAX_FILE_SIZE_BYTES} bytes.",
        )

    if size_bytes == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    file_id = str(uuid.uuid4())
    blob_name = f"{file_id}_{original_filename}"

    try:
        blob_service_client = _get_blob_service_client()
        blob_client = blob_service_client.get_blob_client(
            container=UPLOAD_CONTAINER_NAME, blob=blob_name
        )
        blob_client.upload_blob(file_bytes, overwrite=False)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Failed to save file to blob storage: {exc}"
        )

    return UploadResponse(
        file_id=file_id,
        filename=original_filename,
        size_bytes=size_bytes,
        summary="Parsing not yet implemented — file saved to blob only.",
        truncated=False,
    )
