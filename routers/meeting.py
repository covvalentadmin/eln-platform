"""
routers/meeting.py — ELN Meeting Copilot
POST /api/ai/speech          — audio transcription via Azure Speech SDK
POST /api/ai/meeting         — transcript → structured report → Word doc → blob
GET  /api/ai/meeting/reports — list all meeting reports
"""

import os
import io
import re
import json
import time
import uuid
import asyncio
import logging
import httpx
import pyodbc
from datetime import datetime, date
from typing import Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
AOAI_ENDPOINT    = os.environ.get("AOAI_ENDPOINT", "https://aoai-eln-covvalent-2e2ec.openai.azure.com")
AOAI_DEPLOYMENT  = "gpt-4o"
AOAI_API_VERSION = "2024-12-01-preview"
SPEECH_REGION    = os.environ.get("SPEECH_REGION", "centralindia")
SPEECH_RESOURCE  = os.environ.get("SPEECH_RESOURCE", "speech-eln-covvalent")
SUBSCRIPTION_ID  = "9e25d11c-3753-4b8c-a575-0bcc44f964d4"
RESOURCE_GROUP   = "rg-eln-covvalent"
STORAGE_ACCOUNT  = "stelncoovalent"
BLOB_CONTAINER   = "eln-reports"

# ── Pydantic models ───────────────────────────────────────────────────────────
class MeetingRequest(BaseModel):
    transcript:   str
    project_code: Optional[str] = None
    author:       str = ""

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

def _clean(rows):
    return [{k: _serialize(v) for k, v in row.items()} for row in rows]

def _rows_to_dicts(cur):
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]

# ── Project directory (product-name → project_code resolution) ──────────────
def _get_project_directory(conn) -> list:
    """Returns [{project_code, product_name, generic_name, cas_number}, ...]
    for every project, for product-name-to-project_code resolution."""
    cur = conn.cursor()
    cur.execute("""
        SELECT project_code, title AS product_name, generic_name, cas_number
        FROM eln_projects
        ORDER BY project_code
    """)
    return _clean(_rows_to_dicts(cur))

_directory_cache = {"data": None, "fetched_at": 0}
_DIRECTORY_TTL_SECONDS = 600  # 10 minutes

def get_project_directory_cached(conn) -> list:
    now = time.time()
    if _directory_cache["data"] is None or (now - _directory_cache["fetched_at"]) > _DIRECTORY_TTL_SECONDS:
        _directory_cache["data"] = _get_project_directory(conn)
        _directory_cache["fetched_at"] = now
    return _directory_cache["data"]

# ── Speech key via managed identity ──────────────────────────────────────────
def _get_speech_key() -> str:
    """Retrieve Cognitive Services key using managed identity credentials."""
    from azure.identity import ManagedIdentityCredential
    from azure.mgmt.cognitiveservices import CognitiveServicesManagementClient
    cred   = ManagedIdentityCredential()
    client = CognitiveServicesManagementClient(cred, SUBSCRIPTION_ID)
    keys   = client.accounts.list_keys(RESOURCE_GROUP, SPEECH_RESOURCE)
    return keys.key1

# ── Blocking SDK transcription — run via executor ─────────────────────────────
def _transcribe_sync(audio_path: str) -> tuple:
    import azure.cognitiveservices.speech as speechsdk

    speech_key = _get_speech_key()
    cfg = speechsdk.SpeechConfig(subscription=speech_key, region=SPEECH_REGION)
    cfg.speech_recognition_language = "en-IN"

    auto_detect = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
        languages=["en-IN", "hi-IN"]
    )
    audio_cfg  = speechsdk.audio.AudioConfig(filename=audio_path)
    recognizer = speechsdk.SpeechRecognizer(
        speech_config=cfg,
        audio_config=audio_cfg,
        auto_detect_source_language_config=auto_detect,
    )

    result = recognizer.recognize_once()

    if result.reason == speechsdk.ResultReason.RecognizedSpeech:
        lang = result.properties.get(
            speechsdk.PropertyId.SpeechServiceConnection_AutoDetectSourceLanguageResult,
            "en-IN",
        )
        return result.text, lang
    elif result.reason == speechsdk.ResultReason.Canceled:
        details = speechsdk.CancellationDetails.from_result(result)
        raise RuntimeError(f"Speech recognition canceled: {details.error_details}")
    else:
        return "", str(result.reason)


async def _transcribe_audio(audio_bytes: bytes, content_type: str) -> tuple:
    # Determine file extension for temp file
    ct = content_type.split(";")[0].strip().lower()
    ext_map = {
        "audio/wav":     ".wav",
        "audio/webm":    ".webm",
        "video/webm":    ".webm",
        "audio/mp4":     ".mp4",
        "audio/x-m4a":   ".mp4",
        "audio/ogg":     ".ogg",
        "audio/mpeg":    ".mp3",
    }
    suffix   = ext_map.get(ct, ".wav")
    tmp_path = f"/tmp/{uuid.uuid4()}{suffix}"

    try:
        with open(tmp_path, "wb") as f:
            f.write(audio_bytes)
        loop = asyncio.get_event_loop()
        text, lang = await loop.run_in_executor(None, _transcribe_sync, tmp_path)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    return text, lang

# ── GPT call ──────────────────────────────────────────────────────────────────
async def _call_gpt(system_prompt: str, user_content: str) -> str:
    from azure.identity.aio import DefaultAzureCredential
    cred  = DefaultAzureCredential()
    token = await cred.get_token("https://cognitiveservices.azure.com/.default")
    await cred.close()

    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(
            f"{AOAI_ENDPOINT}/openai/deployments/{AOAI_DEPLOYMENT}/chat/completions"
            f"?api-version={AOAI_API_VERSION}",
            headers={"Authorization": f"Bearer {token.token}", "Content-Type": "application/json"},
            json={
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_content},
                ],
                "max_tokens":  4096,
                "temperature": 0.3,
            },
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

# ── Parse GPT section output ──────────────────────────────────────────────────
SECTION_RE = re.compile(
    r"##\s*(CONTEXT|HYPOTHESIS REVIEW|EXPERIMENT PLAN|RISKS?|CANDIDATE_NOTES|EMAIL_DRAFT)\s*\n",
    re.IGNORECASE
)

_SECTION_KEY_MAP = {
    "context":            "context",
    "hypothesis review":  "hypotheses",
    "experiment plan":    "experiment_plan",
    "risk":               "risks",
    "risks":              "risks",
    "candidate_notes":    "candidate_notes",
    "email_draft":        "email_draft",
}

def _parse_sections(gpt_text: str) -> dict:
    parts = SECTION_RE.split(gpt_text)
    sections: dict = {}
    if len(parts) > 2:
        for i in range(1, len(parts) - 1, 2):
            header  = parts[i].lower().strip().rstrip("s")
            content = parts[i + 1].strip()
            key = _SECTION_KEY_MAP.get(parts[i].lower().strip(), parts[i].lower().strip())
            sections[key] = content
    if not sections:
        sections["full"] = gpt_text
    return sections

def _extract_topic(gpt_text: str) -> str:
    m = re.search(r"##\s*CONTEXT\s*\n+(.+)", gpt_text, re.IGNORECASE)
    if m:
        return m.group(1).strip()[:60]
    lines = [l.strip() for l in gpt_text.split("\n") if l.strip() and not l.startswith("#")]
    return lines[0][:60] if lines else "meeting"

def _slug(text: str, max_len: int = 40) -> str:
    clean = re.sub(r"[^\w\s-]", "", text).strip()
    return re.sub(r"\s+", "-", clean).lower()[:max_len]

def _strip_json_fence(text: str) -> str:
    """Strip a ```json ... ``` (or bare ``` ... ```) fence around a GPT section."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"```\s*$", "", text)
    return text.strip()

# ── Word doc builder ──────────────────────────────────────────────────────────
def _set_cell_shading(cell, hex_color: str):
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    tcPr = cell._tc.get_or_add_tcPr()
    shd  = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color.lstrip("#"))
    tcPr.append(shd)


def _build_meeting_report_docx(
    topic:          str,
    project_code:   Optional[str],
    author:         str,
    gpt_sections:   dict,
    generated_date: str,
) -> bytes:
    from docx import Document
    from docx.shared import Pt, RGBColor, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    RGB = RGBColor

    doc    = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(11)

    # Footer
    fp = doc.sections[0].footer.paragraphs[0]
    fp.text      = (
        f"Covvalent / Rainboweucalyptus Technologies Pvt. Ltd. "
        f"| Confidential | {generated_date}"
    )
    fp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    for run in fp.runs:
        run.font.name      = "Arial"
        run.font.size      = Pt(9)
        run.font.color.rgb = RGB(0x00, 0x0B, 0x36)

    # ── Cover page ──────────────────────────────────────────────────────────
    tbl  = doc.add_table(rows=1, cols=1)
    cell = tbl.cell(0, 0)
    _set_cell_shading(cell, "000B36")
    tbl.rows[0].height = Inches(9)

    def cp(text, size, bold=False, color=None):
        p   = cell.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(text)
        run.font.name  = "Arial"
        run.font.size  = Pt(size)
        run.font.bold  = bold
        run.font.color.rgb = RGB(*color) if color else RGB(0xFF, 0xFF, 0xFF)

    cell.paragraphs[0].clear()
    cp("\n\nCOVVALENT", 24, bold=True)
    cp("ELN Intelligence — R&D Meeting Copilot", 18, color=(0x9D, 0xD1, 0xF1))
    cp(f"\n{topic}", 14, bold=True)
    if project_code:
        cp(f"Project: {project_code}", 12, color=(0x9D, 0xD1, 0xF1))
    cp(f"\n{generated_date} | {author or 'unknown'}", 11)
    cp("\nCONFIDENTIAL", 10, bold=True)
    doc.add_page_break()

    BODY_SECTIONS = [
        ("Context",           gpt_sections.get("context")),
        ("Hypothesis Review", gpt_sections.get("hypotheses")),
        ("Experiment Plan",   gpt_sections.get("experiment_plan")),
        ("Risks",             gpt_sections.get("risks")),
        ("Analysis",          gpt_sections.get("full")),
    ]

    for idx, (title, content) in enumerate(BODY_SECTIONS):
        if not content:
            continue
        h = doc.add_heading(f"Section {idx + 1}: {title}", level=1)
        for run in h.runs:
            run.font.name      = "Arial"
            run.font.color.rgb = RGB(0x00, 0x0B, 0x36)
        for para in content.split("\n\n"):
            if para.strip():
                bp = doc.add_paragraph(para.strip())
                for run in bp.runs:
                    run.font.name      = "Arial"
                    run.font.size      = Pt(11)
                    run.font.color.rgb = RGB(0x0E, 0x26, 0x73)
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
    cred        = DefaultAzureCredential()
    try:
        async with BlobServiceClient(account_url=account_url, credential=cred) as svc:
            try:
                await svc.create_container(BLOB_CONTAINER)
            except Exception:
                pass
            await svc.get_blob_client(
                container=BLOB_CONTAINER, blob=blob_path
            ).upload_blob(content, overwrite=True)
    finally:
        await cred.close()
    return f"{account_url}/{BLOB_CONTAINER}/{blob_path}"

# ── Meeting copilot system prompt ─────────────────────────────────────────────
MEETING_SYSTEM = """
You are the R&D Meeting Co-Pilot for Covvalent, a specialty chemicals CDMO in India.
You receive R&D meeting transcripts in English, Hinglish (Hindi-English mix), or any
combination. Your output is ALWAYS in English regardless of input language.

Analyse the transcript and produce a structured report with EXACTLY these six
sections (use these exact headers):

## CONTEXT
One paragraph only. What process/step is being discussed, what problem exists,
what the team is trying to achieve. No hypotheses or analysis here.

## HYPOTHESIS REVIEW
Bulleted list. For each hypothesis in the transcript:
- Sound: [hypothesis statement] (Verdict: Sound) — no reasoning needed
- Off: [hypothesis] — 1-3 lines on what is wrong and why
- Needs sharpening: [hypothesis] — 1-3 lines reframing it precisely
Then add: Added by reviewer: [hypothesis the team missed] — 1-3 lines on
mechanism and plausibility

## EXPERIMENT PLAN
First: one paragraph stating DoE family choice and expected stop point.
Then numbered bullets: [Factor varied] | [Range/levels] | [Response measured] |
[Stop/proceed rule]

## RISKS
2-5 bullets only. Major safety risks of the PROPOSED experiments: exotherm,
pressure, gas evolution, reactive intermediates, runaway risk. One sentence each.

## CANDIDATE_NOTES
A JSON array (in a fenced ```json block) of project-memory candidates found in
the transcript. Two categories only:
- "decision": strategic/process decisions — route changes, abandoned
  approaches, procedural changes ("we decided to...", "dropping the...",
  "holding at...")
- "data_point": a reported measured value or correction not certain to be in
  the ELN yet — especially if described as approximate, recalled from memory,
  or contradicting a logged value.
Each item: {"note_type": "decision"|"data_point", "note_text": "...",
"exp_number_full": "..."|null, "project_code": "..."|null}
note_text must be the FULL, complete statement with real context — do not
truncate to a fake one-liner. Do not invent items not grounded in the
transcript. If nothing qualifies, return an empty array.

Resolving project codes: A PROJECT DIRECTORY appears before the transcript,
listing every project_code alongside its product name, generic name, and CAS
number. For every candidate note, resolve project_code by matching whatever
product is actually being discussed in that part of the transcript against the
directory — including informal references ("the sulfonation project",
"tryptophan work"). Different candidates in the same meeting may belong to
different projects if more than one product was discussed — resolve each one
independently, do not apply one project_code to all candidates by default. If
no directory entry matches with reasonable confidence, set project_code to
null. Do not guess a project_code from a vague or ambiguous reference.

## EMAIL_DRAFT
A JSON object (in a fenced ```json block): {"subject": "...", "body": "..."}
- subject: "Meeting Summary — <topic/project(s)> — <date>"
  Use the PROJECT DIRECTORY the same way to name every project actually
  discussed in the subject line (e.g. "Meeting Summary — O031C00 / H000E02 —
  <date>"), not just the project_code the request was filed under, since a
  meeting may cover more than one product.
- body:
  1. One short paragraph (1-3 sentences) framing what was discussed.
  2. "Decisions & Next Steps:" — numbered list. Each item states the
     decision/finding in one sentence, then "-> " followed by the specific
     actionable next step.
  3. One closing sentence on safety flags, or state none were raised.
  4. Keep the body under ~280 words total (roughly a 2-minute read). If there
     are more than 5 decisions, include only the 5 most consequential and add
     "(N additional items covered in the full report)".

Language rules: Read Hinglish naturally. Filler words (bhai, yaar, na, toh,
achha) carry no chemistry — ignore them. Technical terms in English carry the
meaning. Output in English.
"""

# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/api/ai/speech")
async def transcribe_speech(
    audio:      Optional[UploadFile] = File(None),
    transcript: Optional[str]        = Form(None),
):
    """Transcribe audio via Azure Speech SDK, or pass through a text transcript."""
    if transcript:
        return {"transcript": transcript, "language_detected": "text"}
    if not audio:
        raise HTTPException(400, detail="Provide either an audio file or a transcript field.")

    audio_bytes  = await audio.read()
    content_type = audio.content_type or "audio/wav"

    try:
        text, lang = await _transcribe_audio(audio_bytes, content_type)
    except RuntimeError as e:
        raise HTTPException(502, detail=str(e))
    except Exception as e:
        raise HTTPException(500, detail=f"Transcription failed: {e}")

    return {"transcript": text, "language_detected": lang}


@router.post("/api/ai/meeting")
async def generate_meeting_report(req: MeetingRequest):
    """Run meeting transcript through copilot prompt, generate Word report, upload to blob."""
    if not req.transcript.strip():
        raise HTTPException(400, detail="Transcript is empty.")

    conn = _get_conn()

    directory = get_project_directory_cached(conn)
    logger.info(f"Loaded {len(directory)} projects for resolution")

    directory_json = json.dumps(directory, ensure_ascii=False)
    user_content = (
        "PROJECT DIRECTORY (for resolving product names mentioned in the transcript to "
        "their project_code — match on product name, generic name, or CAS number, even "
        "if referenced informally):\n"
        f"{directory_json}\n\n"
        f"TRANSCRIPT:\n\n{req.transcript[:8000]}"
    )

    gpt_output = await _call_gpt(MEETING_SYSTEM, user_content)

    sections       = _parse_sections(gpt_output)
    topic          = _extract_topic(gpt_output)
    generated_date = datetime.utcnow().strftime("%Y-%m-%d")
    slug           = _slug(topic)
    filename       = f"{generated_date}-{slug}-meeting.docx"
    blob_path      = f"meetings/{filename}"

    # ── Candidate project-memory notes ────────────────────────────────────
    candidate_notes = []
    raw_candidates  = sections.get("candidate_notes", "")
    if raw_candidates:
        try:
            parsed = json.loads(_strip_json_fence(raw_candidates))
            if isinstance(parsed, list):
                candidate_notes = [item for item in parsed if isinstance(item, dict)]
        except (json.JSONDecodeError, ValueError) as e:
            print(f"[MEETING WARNING] Failed to parse CANDIDATE_NOTES JSON: {e}")

    # ── Email draft ────────────────────────────────────────────────────────
    email_draft = {"subject": "", "body": ""}
    raw_email   = sections.get("email_draft", "")
    if raw_email:
        try:
            parsed = json.loads(_strip_json_fence(raw_email))
            if isinstance(parsed, dict):
                email_draft = {
                    "subject": parsed.get("subject", ""),
                    "body":    parsed.get("body", ""),
                }
        except (json.JSONDecodeError, ValueError) as e:
            print(f"[MEETING WARNING] Failed to parse EMAIL_DRAFT JSON: {e}")

    docx_bytes = _build_meeting_report_docx(
        topic, req.project_code, req.author, sections, generated_date
    )
    blob_url = await _upload_blob(docx_bytes, blob_path)

    cur = conn.cursor()
    cur.execute(
        "INSERT INTO eln_meeting_reports "
        "(project_code, topic, blob_url, transcript, author, status) "
        "OUTPUT INSERTED.report_id, INSERTED.generated_date "
        "VALUES (?,?,?,?,?,'complete')",
        req.project_code, topic[:200], blob_url, req.transcript[:8000], req.author
    )
    row = cur.fetchone()
    report_id  = row[0]
    db_date    = _serialize(row[1])
    conn.commit()
    conn.close()

    for item in candidate_notes:
        # Priority: (1) model's directory-resolved project_code, (2) the
        # meeting's own project_code param if the model returned null,
        # (3) otherwise stays null.
        if not item.get("project_code"):
            item["project_code"] = req.project_code
        item["source_report_id"] = report_id

    return {
        "report_id":       report_id,
        "blob_url":        blob_url,
        "topic":           topic,
        "generated_date":  db_date,
        "filename":        filename,
        "candidate_notes": candidate_notes,
        "email_draft":     email_draft,
    }


@router.get("/api/ai/meeting/reports")
def get_meeting_reports():
    """All meeting reports, newest first."""
    conn = _get_conn()
    cur  = conn.cursor()
    cur.execute(
        "SELECT report_id, project_code, topic, blob_url, author, generated_date, status "
        "FROM eln_meeting_reports ORDER BY generated_date DESC"
    )
    reports = _clean(_rows_to_dicts(cur))
    conn.close()
    return {"reports": reports}
