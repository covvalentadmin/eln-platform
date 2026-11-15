"""Thin client for Clappia's public REST API (stdlib only).

Endpoints (confirmed 2026-11-15 against the official Postman collection at developer.clappia.com):
  POST {base}/submissions/create          body {appId, workplaceId, requestingUserEmailAddress, data}
                                          -> {"submissionId": ..., "submissionFieldValues": {...}}
  POST {base}/submissions/edit            body {appId, workplaceId, requestingUserEmailAddress, submissionId, data}
  POST {base}/submissions/getSubmissions  body {appId, workplaceId, requestingUserEmailAddress,
                                                pageSize, forward, filters, lastSubmissionId?}
                                          -> {"submissions": [{"submissionId", "submissionFieldValues", ...}],
                                              "metadata": {...}, "lastSubmissionId": ...}
Auth: header `x-api-key: <workplace API key>`.

The API key is never logged, printed or included in exceptions.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Optional

DEFAULT_BASE_URL = "https://api-public-v4.clappia.com"
DEFAULT_DOTENV = Path(__file__).resolve().parent.parent / ".env"
PAGE_SIZE = 100
MAX_PAGES = 200  # hard stop against a pagination loop

# transport(url, headers, body_dict, timeout) -> parsed JSON dict. Swapped out in tests.
Transport = Callable[[str, dict, dict, float], dict]


class ClappiaError(RuntimeError):
    pass


# ---------------------------------------------------------------- config
def load_dotenv(path: Optional[Path] = DEFAULT_DOTENV, environ: Optional[dict] = None) -> None:
    """Tiny .env parser: KEY=VALUE lines, # comments, optional quotes. Never overrides existing vars."""
    environ = os.environ if environ is None else environ
    if path is None or not Path(path).is_file():
        return
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:]
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        if k and k not in environ:
            environ[k] = v


@dataclass(frozen=True)
class Config:
    api_key: str = field(default="", repr=False)
    base_url: str = DEFAULT_BASE_URL
    workplace_id: str = "COV908887"
    user_email: str = ""
    app_project_master: str = "SGT708875"
    app_gate_items: str = "SGT584136"
    app_gate_decision: str = "SGT087528"
    enabled: bool = False
    timeout: float = 30.0

    @classmethod
    def from_env(cls, env: Optional[Mapping] = None) -> "Config":
        e = os.environ if env is None else env
        g = lambda k, d="": (e.get(k) or d).strip()  # noqa: E731
        return cls(
            api_key=g("CLAPPIA_API_KEY"),
            base_url=g("CLAPPIA_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
            workplace_id=g("CLAPPIA_WORKPLACE_ID", cls.workplace_id),
            user_email=g("CLAPPIA_USER_EMAIL"),
            app_project_master=g("SG_APP_PROJECT_MASTER", cls.app_project_master),
            app_gate_items=g("SG_APP_GATE_ITEMS", cls.app_gate_items),
            app_gate_decision=g("SG_APP_GATE_DECISION", cls.app_gate_decision),
            enabled=g("SG_ENABLED").lower() == "true",
            timeout=float(g("CLAPPIA_TIMEOUT", "30")),
        )

    def missing_for_live(self) -> list:
        need = {"CLAPPIA_API_KEY": self.api_key, "CLAPPIA_WORKPLACE_ID": self.workplace_id,
                "CLAPPIA_USER_EMAIL": self.user_email}
        return [k for k, v in need.items() if not v]


# ---------------------------------------------------------------- transport
def urllib_transport(url: str, headers: dict, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as ex:
        detail = ex.read().decode("utf-8", "replace")[:500]
        raise ClappiaError(f"HTTP {ex.code} from {url}: {detail}") from None
    except urllib.error.URLError as ex:
        raise ClappiaError(f"network error calling {url}: {ex.reason}") from None
    try:
        return json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        raise ClappiaError(f"non-JSON response from {url}: {raw[:200]}") from None


# ---------------------------------------------------------------- client
class ClappiaClient:
    def __init__(self, cfg: Config, transport: Transport = urllib_transport):
        if not cfg.api_key:
            raise ClappiaError("CLAPPIA_API_KEY is not set")
        self.cfg = cfg
        self._transport = transport

    def __repr__(self) -> str:  # never expose the key
        return f"ClappiaClient(base_url={self.cfg.base_url!r}, workplace_id={self.cfg.workplace_id!r})"

    def _post(self, path: str, body: dict) -> dict:
        headers = {"x-api-key": self.cfg.api_key, "Content-Type": "application/json"}
        payload = {"workplaceId": self.cfg.workplace_id,
                   "requestingUserEmailAddress": self.cfg.user_email, **body}
        out = self._transport(f"{self.cfg.base_url}{path}", headers, payload, self.cfg.timeout)
        if isinstance(out, dict) and out.get("error"):
            raise ClappiaError(f"{path}: {out['error']}")
        return out

    def create_submission(self, app_id: str, data: dict) -> str:
        out = self._post("/submissions/create", {"appId": app_id, "data": data})
        sid = out.get("submissionId")
        if not sid:
            raise ClappiaError(f"create on {app_id} returned no submissionId")
        return sid

    def edit_submission(self, app_id: str, submission_id: str, data: dict) -> None:
        self._post("/submissions/edit", {"appId": app_id, "submissionId": submission_id, "data": data})

    def get_submissions(self, app_id: str, equals: Optional[dict] = None) -> list:
        """All submissions in app_id whose custom fields equal `equals` (AND). Follows pagination."""
        conditions = [{"operator": "EQ", "filterKeyType": "CUSTOM", "key": k, "value": str(v)}
                      for k, v in (equals or {}).items()]
        body = {"appId": app_id, "pageSize": PAGE_SIZE, "forward": True}
        if conditions:
            body["filters"] = {"queries": [{"queries": [], "conditions": conditions, "operator": "AND"}],
                               "conditions": [], "operator": "AND"}
        results, last = [], None
        for _ in range(MAX_PAGES):
            page_body = dict(body, lastSubmissionId=last) if last else body
            out = self._post("/submissions/getSubmissions", page_body)
            page = out.get("submissions") or []
            results.extend(page)
            nxt = out.get("lastSubmissionId")
            if len(page) < PAGE_SIZE or not nxt or nxt == last:
                break
            last = nxt
        else:
            raise ClappiaError(f"getSubmissions on {app_id} exceeded {MAX_PAGES} pages")
        # belt and braces: re-apply the filter client-side
        return [s for s in results
                if all(str(fv(s).get(k, "")) == str(v) for k, v in (equals or {}).items())]


def fv(submission: dict) -> dict:
    """Field values of a getSubmissions record."""
    return submission.get("submissionFieldValues") or {}
