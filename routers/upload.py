"""
routers/upload.py
POST /api/ai/upload — accepts a PDF/Excel/CSV file, validates it, saves
the original to Azure Blob Storage (container: eln-chat-uploads), and
returns a capped, human-readable summary for the AI Chat agent.

PDF: pdfplumber text extraction first (fast, free). If that comes back
     empty or below a meaningful content threshold — e.g. a PDF whose
     body content is embedded as images/vector graphics rather than a
     real text layer — falls back to Azure AI Document Intelligence
     (prebuilt-layout, markdown output) for OCR. OCR is a paid
     per-page call, so it's only invoked as a fallback, never on every
     upload.
Excel/CSV: pandas — sheet names, headers, row count, first N rows,
     basic stats per numeric column.
"""

import asyncio
import io
import os
import uuid
from typing import Optional

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
MIN_CHARS_PER_PAGE = 50  # below this average, treat extraction as unreliable —
                          # a real text page normally runs into the hundreds+
                          # of characters; PDFs whose body content is vector-
                          # drawn (tables/diagrams with no real text layer,
                          # only incidental headings) land far below this

# OCR fallback (Azure AI Document Intelligence). Read softly with .get(), NOT
# os.environ[...] — a missing/misconfigured setting here must degrade this one
# feature (OCR unavailable) rather than crash the whole app at import time,
# the same class of failure that took down the entire API on 22 Jul 2026.
DOCUMENT_INTELLIGENCE_ENDPOINT = os.environ.get("DOCUMENT_INTELLIGENCE_ENDPOINT")
OCR_MODEL_ID = "prebuilt-layout"  # over prebuilt-read: these are lab spec/MoA
                                   # documents with real tables worth preserving
                                   # as structure, not just flattened text
OCR_TIMEOUT_SECONDS = 60


class UploadResponse(BaseModel):
    file_id: str
    filename: str
    size_bytes: int
    summary: str
    truncated: bool
    used_ocr: bool


def _get_blob_service_client() -> BlobServiceClient:
    account_url = f"https://{STORAGE_ACCOUNT_NAME}.blob.core.windows.net"
    credential = ManagedIdentityCredential()
    return BlobServiceClient(account_url=account_url, credential=credential)


async def _ocr_pdf(file_bytes: bytes) -> Optional[str]:
    """
    Fallback OCR via Azure AI Document Intelligence (prebuilt-layout,
    markdown output — preserves tables as real markdown tables rather than
    flattened text). Returns the extracted content, or None if OCR isn't
    configured or the call fails for any reason — callers must treat None
    as "OCR unavailable", not as an error to propagate; the pdfplumber
    result (however sparse) is always the safe fallback-of-the-fallback.
    """
    if not DOCUMENT_INTELLIGENCE_ENDPOINT:
        print("_ocr_pdf: DOCUMENT_INTELLIGENCE_ENDPOINT not configured — OCR unavailable")
        return None

    try:
        from azure.ai.documentintelligence.aio import DocumentIntelligenceClient
        from azure.ai.documentintelligence.models import AnalyzeDocumentRequest, DocumentContentFormat
        from azure.identity.aio import ManagedIdentityCredential as AsyncManagedIdentityCredential

        async def _run_ocr():
            credential = AsyncManagedIdentityCredential()
            try:
                async with DocumentIntelligenceClient(
                    endpoint=DOCUMENT_INTELLIGENCE_ENDPOINT, credential=credential
                ) as client:
                    poller = await client.begin_analyze_document(
                        OCR_MODEL_ID,
                        AnalyzeDocumentRequest(bytes_source=file_bytes),
                        output_content_format=DocumentContentFormat.MARKDOWN,
                    )
                    result = await poller.result()
                    return result.content or None
            finally:
                await credential.close()

        return await asyncio.wait_for(_run_ocr(), timeout=OCR_TIMEOUT_SECONDS)

    except asyncio.TimeoutError:
        print(f"_ocr_pdf: OCR call exceeded {OCR_TIMEOUT_SECONDS}s timeout")
        return None
    except Exception as exc:
        print(f"_ocr_pdf: OCR call failed: {type(exc).__name__}: {exc}")
        return None


async def _parse_pdf(file_bytes: bytes) -> tuple:
    """Returns (summary_text, used_ocr)."""
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
        return f"PDF parsing failed: {exc}", False

    avg_chars_per_page = (len(full_text) / num_pages) if num_pages else 0
    needs_ocr = (not full_text) or (avg_chars_per_page < MIN_CHARS_PER_PAGE)

    if needs_ocr:
        ocr_text = await _ocr_pdf(file_bytes)
        if ocr_text:
            return f"PDF text extract via OCR ({num_pages} page(s)):\n\n{ocr_text}", True

        # OCR unavailable or failed — fall back to whatever pdfplumber found,
        # clearly flagged as unreliable rather than presented as complete.
        if not full_text:
            return (
                f"PDF has {num_pages} page(s) but text extraction returned no "
                "content — this looks like a scanned/image-based PDF, and "
                "OCR fallback was unavailable or failed for this file.",
                False,
            )
        return (
            f"PDF has {num_pages} page(s) but text extraction returned only "
            f"{len(full_text)} characters total — most of this document is "
            "likely vector-drawn (tables, diagrams, or scanned content) "
            "rather than real embedded text, and OCR fallback was "
            "unavailable or failed for this file. Only incidental text "
            f"(e.g. headings) was found:\n\n{full_text}",
            False,
        )

    return f"PDF text extract ({num_pages} page(s)):\n\n{full_text}", False


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
        summary_text, used_ocr = await _parse_pdf(file_bytes)
    else:
        summary_text = _parse_tabular(file_bytes, ext)
        used_ocr = False

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
        used_ocr=used_ocr,
    )
