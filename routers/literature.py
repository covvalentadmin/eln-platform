"""
routers/literature.py — Tool 3: External literature search
GET /api/ai/literature
Sources: PubChem (compound profiles) + CrossRef (academic papers)
"""

import httpx
from fastapi import APIRouter, HTTPException, Query

router = APIRouter()

PUBCHEM_BASE  = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
CROSSREF_BASE = "https://api.crossref.org/works"

@router.get("/api/ai/literature")
async def literature(q: str = Query(..., min_length=2)):
    results = {"query": q, "pubchem": [], "crossref": []}

    async with httpx.AsyncClient(timeout=20.0) as client:

        # ── PubChem ───────────────────────────────────────────────────────────
        try:
            # Search by name
            r = await client.get(
                f"{PUBCHEM_BASE}/compound/name/{httpx.URL(q).path}/JSON"
            )
            if r.status_code == 200:
                data = r.json()
                compounds = data.get("PC_Compounds", [])[:3]
                for c in compounds:
                    props = {p["urn"]["label"]: p.get("value", {})
                             for p in c.get("props", [])
                             if "label" in p.get("urn", {})}
                    cid = c.get("id", {}).get("id", {}).get("cid")
                    results["pubchem"].append({
                        "cid":          cid,
                        "name":         props.get("IUPAC Name", {}).get("sval", q),
                        "formula":      props.get("Molecular Formula", {}).get("sval"),
                        "mol_weight":   props.get("Molecular Weight", {}).get("fval"),
                        "canonical_smiles": props.get("SMILES", {}).get("sval"),
                        "url":          f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}" if cid else None
                    })
        except Exception:
            pass  # PubChem failure is non-fatal

        # ── CrossRef ──────────────────────────────────────────────────────────
        try:
            r = await client.get(
                CROSSREF_BASE,
                params={
                    "query": q,
                    "rows":  5,
                    "select": "DOI,title,author,published,container-title,abstract"
                }
            )
            if r.status_code == 200:
                items = r.json().get("message", {}).get("items", [])
                for item in items:
                    authors = item.get("author", [])
                    author_str = ", ".join(
                        f"{a.get('given','')} {a.get('family','')}".strip()
                        for a in authors[:3]
                    )
                    pub_date = item.get("published", {}).get("date-parts", [[]])[0]
                    results["crossref"].append({
                        "doi":        item.get("DOI"),
                        "title":      (item.get("title") or [""])[0],
                        "authors":    author_str,
                        "year":       pub_date[0] if pub_date else None,
                        "journal":    (item.get("container-title") or [""])[0],
                        "abstract":   (item.get("abstract") or "")[:500],
                        "url":        f"https://doi.org/{item.get('DOI')}" if item.get("DOI") else None
                    })
        except Exception:
            pass  # CrossRef failure is non-fatal

    if not results["pubchem"] and not results["crossref"]:
        raise HTTPException(404, detail=f"No literature results found for: {q}")

    return results
