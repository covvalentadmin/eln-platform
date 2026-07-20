"""
routers/upload.py
POST /api/ai/upload — accepts a PDF/Excel/CSV file, validates it, saves
the original to Azure Blob Storage (container: eln-chat-uploads), and
returns a capped, human-readable summary for the AI Chat agent.

PDF: pdfplumber text extraction. Empty extraction is flagged as
     "needs OCR" rather than silently failing.
Excel/CSV: pandas — sheet names, headers, row count, first N rows,
     basic stats per numeric column.
"""

import io
import os
import uuid

import pandas as pd
import pdfplumber
from azure.identity import ManagedIdentityCredential
from azure.storage.blob import BlobServiceClient
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

router = APIRouter()

STORAGE_ACCOUNT_NAME = "stelncoovalent"
UPLOAD_CONTAINER_NAME = "eln-chat-uploads"
ALLOWED_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".csv"}
MAX_FILE_SIZE_BYTES = 15 * 1024 * 1024  # 15MB
MAX_SUMMARY_CHARS = 28000  # ~6-8K tokens at ~4 chars/token
MAX_ROWS_PREVIEW = 10


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


def _parse_pdf(file_bytes: bytes) -> str:
    try:
        text_parts = []
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            num_pages = len(pdf.pages)
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                if page_text.strip():
                    text_parts.append(page_text)
        full_text = "\n\n".join(text_parts).strip()
    except Exception as exc:
        return f"PDF parsing failed: {exc}"

    if not full_text:
        return (
            f"PDF has {num_pages} page(s) but text extraction returned no "
            "content — this looks like a scanned/image-based PDF. OCR is "
            "not yet implemented; only a text layer can be read at this time."
        )

    return f"PDF text extract ({num_pages} page(s)):\n\n{full_text}"


def _parse_tabular(file_bytes: bytes, ext: str) -> str:
    try:
        if ext == ".csv":
            df = pd.read_csv(io.BytesIO(file_bytes))
            sheets = {"Sheet1": df}
        else:  # .xlsx / .xls
            sheets = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None)
    except Exception as exc:
        return f"Tabular parsing failed: {exc}"

    parts = []
    for sheet_name, df in sheets.items():
        parts.append(f"Sheet '{sheet_name}': {df.shape[0]} rows x {df.shape[1]} columns")
        parts.append(f"Columns: {list(df.columns)}")

        preview = df.head(MAX_ROWS_PREVIEW)
        parts.append(f"First {len(preview)} rows:\n{preview.to_string(index=False)}")

        numeric_df = df.select_dtypes(include="number")
        if not numeric_df.empty:
            stats = numeric_df.describe().to_string()
            parts.append(f"Numeric column stats:\n{stats}")

        parts.append("")

    return "\n".join(parts).strip()


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

    if ext == ".pdf":
        summary_text = _parse_pdf(file_bytes)
    else:
        summary_text = _parse_tabular(file_bytes, ext)

    truncated = False
    if len(summary_text) > MAX_SUMMARY_CHARS:
        summary_text = summary_text[:MAX_SUMMARY_CHARS] + "\n\n[...truncated...]"
        truncated = True

    return UploadResponse(
        file_id=file_id,
        filename=original_filename,
        size_bytes=size_bytes,
        summary=summary_text,
        truncated=truncated,
    )
