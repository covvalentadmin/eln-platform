"""
routers/meeting.py — ELN Meeting Copilot
POST /api/ai/speech  — audio transcription via Azure Speech REST API
POST /api/ai/meeting — meeting transcript → structured report → Word doc → blob
"""

import os
import io
import json
import re
import tempfile
import httpx
import pyodbc
from datetime import datetime, date
from typing import Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from pydantic import BaseModel

router = APIRouter()

# ── Config ────────────────────────────────────────────────────────────────────
FOUNDRY_ENDPOINT = os.environ["FOUNDRY_ENDPOINT"]
FOUNDRY_API_VER  = os.environ.get("FOUNDRY_API_VERSION", "2025-05-15-preview")
AGENT_MODEL      = os.environ.get("AGENT_MODEL", "gpt-5-4")
SPEECH_REGION    = os.environ.get("SPEECH_REGION", "southindia")
STORAGE_ACCOUNT  = "stelncoovalent"
BLOB_CONTAINER   = "eln-reports"

# ── Pydantic models ───────────────────────────────────────────────────────────
class MeetingRequest(BaseModel):
    transcript:   str
    project_code: Optional[str] = None
    author:       str = "unknown"

# ── DB helpers ────────────────────────────────────────────────────────────────
def _get_conn():
    conn_str = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={os.environ['SQL_SERVER']};"
        f"DATABASE={os.environ['SQL_DATABASE']};"
        f"UID={os.environ['SQL_USERNAME']};"
        f"PWD={os.environ['SQL_PASSWORD']};"
        f"TrustServerCertificate=yes;"
        f"Connection Timeout=30;"
    )
    return pyodbc.connect(conn_str)

def _serialize(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v

# ── Auth helpers ──────────────────────────────────────────────────────────────
async def _get_foundry_token() -> str:
    from azure.identity.aio import ManagedIdentityCredential
    cred = ManagedIdentityCredential()
    token = await cred.get_token("https://ai.azure.com/.default")
    await cred.close()
    return token.token

async def _get_speech_token() -> str:
    from azure.identity.aio import ManagedIdentityCredential
    cred = ManagedIdentityCredential()
    token = await cred.get_token("https://cognitiveservices.azure.com/.default")
    await cred.close()
    return token.token

# ── Speech transcription ──────────────────────────────────────────────────────
async def _transcribe_audio(audio_bytes: bytes, content_type: str) -> tuple[str, str]:
    """Transcribe audio using Azure Speech REST API (synchronous, ≤60 s audio)."""
    token = await _get_speech_token()
    ct_map = {
        "audio/wav":      "audio/wav; codecs=audio; samplerate=16000",
        "audio/webm":     "audio/webm; codecs=opus",
        "audio/mp4":      "audio/mp4",
        "audio/x-m4a":    "audio/mp4",
        "video/webm":     "audio/webm; codecs=opus",
    }
    api_ct = ct_map.get(content_type.split(";")[0].strip(), "audio/wav")

    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(
            f"https://{SPEECH_REGION}.stt.speech.microsoft.com"
            "/speech/recognition/conversation/cognitiveservices/v1",
            params={"language": "en-IN", "format": "simple", "profanity": "raw"},
            headers={"Authorization": f"Bearer {token}", "Content-Type": api_ct},
            content=audio_bytes,
        )
        r.raise_for_status()
        data = r.json()
        transcript = data.get("DisplayText", "")
        language   = data.get("RecognitionStatus", "Success")
        return transcript, language

# ── GPT call ──────────────────────────────────────────────────────────────────
async def _call_gpt(system_prompt: str, user_content: str, max_tokens: int = 4096) -> str:
    token = await _get_foundry_token()
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(
            f"{FOUNDRY_ENDPOINT}/openai/deployments/{AGENT_MODEL}/chat/completions"
            f"?api-version={FOUNDRY_API_VER}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_content},
                ],
                "max_tokens":  max_tokens,
                "temperature": 0.3,
            },
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

# ── Extract topic from GPT output ─────────────────────────────────────────────
def _extract_topic(gpt_text: str) -> str:
    """Pull the first heading or significant noun phrase as a short topic slug."""
    # Try to find a CONTEXT section heading or first sentence
    match = re.search(r"(?:CONTEXT|TOPIC)[:\s]+([^\n]+)", gpt_text, re.IGNORECASE)
    if match:
        topic = match.group(1).strip()[:60]
    else:
        # First non-empty line
        lines = [l.strip() for l in gpt_text.split("\n") if l.strip()]
        topic = lines[0][:60] if lines else "meeting"
    # Slugify
    return re.sub(r"[^\w\s-]", "", topic).replace(" ", "-").lower()[:40]

# ── Word doc builder ──────────────────────────────────────────────────────────
def _set_cell_shading(cell, hex_color: str):
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color.lstrip("#"))
    tcPr.append(shd)

def _build_meeting_report_docx(
    topic: str,
    project_code: Optional[str],
    author: str,
    gpt_output: str,
    transcript: str,
    generated_date: str,
) -> bytes:
    from docx import Document
    from docx.shared import Pt, RGBColor, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    RGB = RGBColor
    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(11)

    # Footer
    section = doc.sections[0]
    footer  = section.footer
    fp = footer.paragraphs[0]
    fp.text = f"Covvalent / Rainboweucalyptus Technologies Pvt. Ltd. | Confidential | {generated_date}"
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in fp.runs:
        run.font.name = "Arial"
        run.font.size = Pt(9)
        run.font.color.rgb = RGB(0x4A, 0x61, 0x94)

    # Cover page
    tbl = doc.add_table(rows=1, cols=1)
    cell = tbl.cell(0, 0)
    _set_cell_shading(cell, "000B36")
    tbl.rows[0].height = Inches(9)

    def _cp(text, size, bold=False, color=None):
        p = cell.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(text)
        run.font.name = "Arial"
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = RGB(*color) if color else RGB(0xFF, 0xFF, 0xFF)

    cell.paragraphs[0].clear()
    _cp("\n\nCOVVALENT", 32, bold=True)
    _cp("ELN Intelligence — R&D Meeting Copilot", 16, color=(0x9D, 0xD1, 0xF1))
    _cp(f"\n{topic}", 14, bold=True)
    if project_code:
        _cp(f"Project: {project_code}", 12, color=(0x9D, 0xD1, 0xF1))
    _cp(f"\n{generated_date} | {author}", 11)
    _cp("\nCONFIDENTIAL", 10, bold=True)
    doc.add_page_break()

    # Split GPT output into the 5 sections
    # Pattern: numbered section headers like "1. CONTEXT" or "## 1. CONTEXT"
    section_pattern = re.compile(
        r"(?:^|\n)(?:#{1,3}\s*)?(\d)\.\s+(CONTEXT|HYPOTHESIS REVIEW|EXPERIMENT PLAN|RISKS?|RECOMMENDATIONS?)[^\n]*",
        re.IGNORECASE
    )
    parts = section_pattern.split(gpt_output)
    # parts = [preamble, num, title, content, num, title, content, ...]
    # Build a dict: {section_num: (title, content)}
    sections = {}
    if len(parts) > 3:
        for i in range(1, len(parts) - 2, 3):
            num     = parts[i].strip()
            title   = parts[i + 1].strip()
            content = parts[i + 2].strip()
            sections[num] = (title, content)

    section_titles = ["CONTEXT", "HYPOTHESIS REVIEW", "EXPERIMENT PLAN", "RISKS", "RECOMMENDATIONS"]
    for num, default_title in enumerate(section_titles, start=1):
        key = str(num)
        title, content = sections.get(key, (default_title, ""))

        p = doc.add_heading(f"Section {num}: {title}", level=1)
        for run in p.runs:
            run.font.name = "Arial"
            run.font.color.rgb = RGB(0x00, 0x0B, 0x36)

        if content:
            for para in content.split("\n\n"):
                if para.strip():
                    bp = doc.add_paragraph(para.strip())
                    for run in bp.runs:
                        run.font.name = "Arial"
                        run.font.size = Pt(11)
                        run.font.color.rgb = RGB(0x0E, 0x26, 0x73)
        else:
            # Fallback: include full GPT output in first section
            if num == 1:
                for para in gpt_output.split("\n\n"):
                    if para.strip():
                        bp = doc.add_paragraph(para.strip())
                        for run in bp.runs:
                            run.font.name = "Arial"
                            run.font.size = Pt(11)
                            run.font.color.rgb = RGB(0x0E, 0x26, 0x73)
                break

        if num < 5:
            doc.add_page_break()

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()

# ── Blob upload ───────────────────────────────────────────────────────────────
async def _upload_blob(content: bytes, blob_path: str) -> str:
    from azure.identity.aio import DefaultAzureCredential
    from azure.storage.blob.aio import BlobServiceClient
    account_url = f"https://{STORAGE_ACCOUNT}.blob.core.windows.net"
    credential  = DefaultAzureCredential()
    try:
        async with BlobServiceClient(account_url=account_url, credential=credential) as svc:
            try:
                await svc.create_container(BLOB_CONTAINER)
            except Exception:
                pass
            blob = svc.get_blob_client(container=BLOB_CONTAINER, blob=blob_path)
            await blob.upload_blob(content, overwrite=True)
    finally:
        await credential.close()
    return f"{account_url}/{BLOB_CONTAINER}/{blob_path}"

# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/api/ai/speech")
async def transcribe_speech(
    audio:      Optional[UploadFile] = File(None),
    transcript: Optional[str]        = Form(None),
):
    """Transcribe audio file, or pass through a provided transcript."""
    if transcript:
        return {"transcript": transcript, "language_detected": "text"}

    if not audio:
        raise HTTPException(400, detail="Provide either audio file or transcript field.")

    audio_bytes  = await audio.read()
    content_type = audio.content_type or "audio/wav"

    try:
        text, lang = await _transcribe_audio(audio_bytes, content_type)
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, detail=f"Speech service error: {e.response.status_code}")
    except Exception as e:
        raise HTTPException(500, detail=str(e))

    return {"transcript": text, "language_detected": lang}


@router.post("/api/ai/meeting")
async def generate_meeting_report(req: MeetingRequest):
    """Run meeting transcript through copilot prompt, generate Word report, upload to blob."""
    if not req.transcript.strip():
        raise HTTPException(400, detail="Transcript is empty.")

    MEETING_SYSTEM = (
        "You are a senior process chemist acting as R&D Meeting Co-Pilot for Covvalent, "
        "a specialty chemicals CDMO. Language: handles English, Hinglish, Hindi-English mix. "
        "Output always in English. Use lab-report language. "
        "Cite specific quotes from the transcript when referencing what was said."
    )

    MEETING_USER = f"""You have received a meeting transcript. Generate a structured report with EXACTLY these five numbered sections:

1. CONTEXT (one paragraph): What step/process is discussed, what problem exists, what the team is trying to change. No analysis yet.

2. HYPOTHESIS REVIEW: For each hypothesis raised:
   - Sound: state hypothesis + (Verdict: Sound). No reasoning needed.
   - Off: 1-3 lines on what's wrong and why.
   - Needs sharpening: 1-3 lines reframing it precisely.
   - Added by reviewer: hypothesis the team missed — 1-3 lines on mechanism and why plausible.

3. EXPERIMENT PLAN: State DoE family and expected stop point (e.g. 'Total: 7 runs. Expected stop at run 3-5 if hypothesis holds.'). Then numbered bullets: Factor | Range | Response | Stop rule.

4. RISKS: 2-5 bullets, major safety risks of proposed experiments only. Exotherm, pressure, gas evolution, reactive intermediates. One sentence each.

5. RECOMMENDATIONS: Priority-ordered next steps with explicit go/no-go criteria.

TRANSCRIPT:
{req.transcript[:8000]}"""

    gpt_output = await _call_gpt(MEETING_SYSTEM, MEETING_USER)

    topic          = _extract_topic(gpt_output)
    generated_date = datetime.utcnow().strftime("%Y-%m-%d")
    safe_topic     = re.sub(r"[^\w-]", "", topic)[:40]
    filename       = f"RnD_Meeting_Copilot_v2_{safe_topic}_{generated_date}.docx"
    blob_path      = f"meetings/{filename}"

    docx_bytes = _build_meeting_report_docx(
        topic, req.project_code, req.author, gpt_output, req.transcript, generated_date
    )
    blob_url = await _upload_blob(docx_bytes, blob_path)

    # Persist record
    conn = _get_conn()
    cur  = conn.cursor()
    cur.execute(
        "INSERT INTO eln_meeting_reports "
        "(project_code, topic, blob_url, transcript, author, status) "
        "OUTPUT INSERTED.report_id, INSERTED.generated_date "
        "VALUES (?,?,?,?,?,'complete')",
        req.project_code, topic[:200], blob_url, req.transcript[:8000], req.author
    )
    row = cur.fetchone()
    report_id      = row[0]
    db_date        = _serialize(row[1])
    conn.commit()
    conn.close()

    return {
        "report_id":      report_id,
        "blob_url":       blob_url,
        "topic":          topic,
        "generated_date": db_date,
        "filename":       filename,
    }
