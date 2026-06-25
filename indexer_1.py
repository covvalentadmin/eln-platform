#!/usr/bin/env python3
"""
ELN AI Insight Engine — Indexer Job (AIE-102 revised)
Reads exported CSVs from Azure Blob Storage, chunks experiments,
embeds with text-embedding-3-large, upserts into Azure AI Search.

Required environment variables:
  STORAGE_ACCOUNT    stelncoovalent
  STORAGE_CONTAINER  eln-analytics
  AOAI_ENDPOINT      https://aoai-eln-covvalent-2e2ec.openai.azure.com/
  SEARCH_ENDPOINT    https://aisrch-eln-covvalent.search.windows.net

Optional:
  AZURE_CLIENT_ID    user-assigned MI client ID
  SEARCH_INDEX       eln-experiments (default)
  BATCH_SIZE         50 (default)
  EXPERIMENT_ID      single experiment ID for testing
"""

import os, sys, logging
from io import StringIO
from typing import Optional

import pandas as pd
from azure.identity import ManagedIdentityCredential
from azure.storage.blob import BlobServiceClient
from azure.search.documents import SearchClient
from openai import AzureOpenAI

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
log = logging.getLogger(__name__)

STORAGE_ACCOUNT   = os.environ["STORAGE_ACCOUNT"]
STORAGE_CONTAINER = os.environ["STORAGE_CONTAINER"]
AOAI_ENDPOINT     = os.environ["AOAI_ENDPOINT"]
SEARCH_ENDPOINT   = os.environ["SEARCH_ENDPOINT"]
SEARCH_INDEX      = os.environ.get("SEARCH_INDEX", "eln-experiments")
BATCH_SIZE        = int(os.environ.get("BATCH_SIZE", "50"))
EXPERIMENT_ID     = os.environ.get("EXPERIMENT_ID")
MAX_CHARS         = 30_000


def build_clients():
    cred = ManagedIdentityCredential()
    token_fn = lambda: cred.get_token("https://cognitiveservices.azure.com/.default").token
    blob = BlobServiceClient(
        account_url=f"https://{STORAGE_ACCOUNT}.blob.core.windows.net",
        credential=cred)
    oai  = AzureOpenAI(azure_endpoint=AOAI_ENDPOINT, azure_ad_token_provider=token_fn, api_version="2024-02-01")
    srch = SearchClient(endpoint=SEARCH_ENDPOINT, index_name=SEARCH_INDEX, credential=cred)
    return blob, oai, srch


def load_csv(blob: BlobServiceClient, table: str) -> pd.DataFrame:
    bc = blob.get_blob_client(container=STORAGE_CONTAINER, blob=f"{table}.csv")
    content = bc.download_blob().readall().decode("utf-8")
    return pd.read_csv(StringIO(content))


def load_tables(blob: BlobServiceClient) -> dict:
    names = ["eln_experiments","eln_experiment_procedure","eln_experiment_materials",
             "eln_experiment_products","eln_experiment_tlc","eln_project_teams","eln_projects"]
    data = {}
    for t in names:
        data[t] = load_csv(blob, t)
        log.info(f"Loaded {t}: {len(data[t])} rows")
    return data


def build_exp_df(data: dict) -> pd.DataFrame:
    exps    = data["eln_experiments"].copy()
    teams   = data["eln_project_teams"][["project_team_id","project_id","team_code"]]
    projs   = data["eln_projects"][["project_id","project_code","title","generic_name","cas_number","iupac_name"]]
    exps    = exps.merge(teams, on="project_team_id", how="left")
    exps    = exps.merge(projs, on="project_id",       how="left", suffixes=("","_proj"))
    if "title_proj" in exps.columns:
        exps = exps.rename(columns={"title_proj":"project_title"})
    elif "title_y" in exps.columns:
        exps = exps.rename(columns={"title_y":"project_title","title_x":"title"})
    return exps


def embed(oai: AzureOpenAI, text: str) -> list:
    return oai.embeddings.create(model="text-embedding-3-large", input=text[:MAX_CHARS]).data[0].embedding


def na(val) -> bool:
    try: return pd.isna(val)
    except: return val is None


def overview_text(exp: pd.Series) -> str:
    p = []
    if not na(exp.get("title")):           p.append(f"Experiment: {exp['title']}")
    if not na(exp.get("exp_number_full")): p.append(f"Number: {exp['exp_number_full']}")
    proj = str(exp.get("project_code","")) if not na(exp.get("project_code")) else ""
    if not na(exp.get("project_title")):   proj += f" — {exp['project_title']}"
    if proj.strip():                       p.append(f"Project: {proj}")
    cmpd = str(exp.get("generic_name","")) if not na(exp.get("generic_name")) else ""
    if cmpd:
        if not na(exp.get("cas_number")):  cmpd += f" (CAS {exp['cas_number']})"
        if not na(exp.get("iupac_name")):  cmpd += f"; IUPAC: {exp['iupac_name']}"
        p.append(f"Target compound: {cmpd}")
    if not na(exp.get("objective")):        p.append(f"Objective: {exp['objective']}")
    if not na(exp.get("conclusion")):       p.append(f"Conclusion: {exp['conclusion']}")
    if not na(exp.get("next_action_plan")): p.append(f"Next actions: {exp['next_action_plan']}")
    return "\n".join(p)


def procedure_text(steps: pd.DataFrame) -> str:
    if steps.empty: return ""
    # Filter header rows if column exists
    if "is_header" in steps.columns:
        steps = steps[~steps["is_header"].astype(str).str.lower().isin(["true","1"])]
    lines = []
    for _, s in steps.iterrows():
        parts = [str(s["operation"]).strip()] if not na(s.get("operation")) else []
        details = []
        if not na(s.get("quantity")):    details.append(f"qty {s['quantity']}")
        if not na(s.get("temperature")): details.append(f"{s['temperature']}C")
        if not na(s.get("time_value")):  details.append(str(s["time_value"]))
        if details: parts.append(f"[{', '.join(details)}]")
        if not na(s.get("observations")): parts.append(f"-> {str(s['observations']).strip()}")
        if parts: lines.append(" ".join(parts))
    return "\n".join(lines)


def results_text(mats: pd.DataFrame, prods: pd.DataFrame, tlc: pd.DataFrame) -> str:
    secs = []
    if not mats.empty:
        ml = []
        for _, m in mats.iterrows():
            s = str(m.get("raw_material_name","?"))
            ex = []
            if not na(m.get("cas_number")):        ex.append(f"CAS {m['cas_number']}")
            if not na(m.get("molecular_formula")):  ex.append(str(m["molecular_formula"]))
            if not na(m.get("quantity")):           ex.append(str(m["quantity"]))
            if not na(m.get("purity")):             ex.append(f"{m['purity']}% purity")
            if str(m.get("is_limiting_agent","")).lower() in ["true","1"]: ex.append("LIMITING")
            if ex: s += f" ({'; '.join(ex)})"
            ml.append(s)
        secs.append("Materials used:\n" + "\n".join(ml))
    if not prods.empty:
        pl = []
        for _, p in prods.iterrows():
            s = str(p.get("product_name","?"))
            ex = []
            if not na(p.get("molecular_formula")): ex.append(str(p["molecular_formula"]))
            if not na(p.get("iupac_name")):        ex.append(str(p["iupac_name"]))
            if not na(p.get("purified_yield")):    ex.append(f"purified yield {p['purified_yield']}%")
            elif not na(p.get("crude_yield")):     ex.append(f"crude yield {p['crude_yield']}%")
            if not na(p.get("purity")):            ex.append(f"purity {p['purity']}%")
            if ex: s += f" ({'; '.join(ex)})"
            pl.append(s)
        secs.append("Products:\n" + "\n".join(pl))
    if not tlc.empty:
        tl = []
        for _, t in tlc.iterrows():
            line = str(t.get("plate_title","TLC"))
            if not na(t.get("plate_notes")): line += f": {t['plate_notes']}"
            spots = []
            for ltr, rfk in [("A","rf1"),("B","rf2"),("C","rf3"),("D","rf4")]:
                note = t.get(f"spot_{ltr.lower()}_notes")
                rf   = t.get(rfk)
                if not na(note) or not na(rf):
                    sp = f"Spot {ltr}"
                    if not na(note): sp += f": {note}"
                    if not na(rf):   sp += f" Rf={rf}"
                    spots.append(sp)
            if spots: line += " | " + "; ".join(spots)
            tl.append(line)
        secs.append("TLC:\n" + "\n".join(tl))
    return "\n\n".join(secs)


def extract_yield(prods: pd.DataFrame):
    if prods.empty: return False, None
    vals = []
    for _, p in prods.iterrows():
        y = p.get("purified_yield") if not na(p.get("purified_yield")) else p.get("crude_yield")
        if not na(y): vals.append(float(y))
    return (True, max(vals)) if vals else (False, None)


def make_doc(exp: pd.Series, chunk_type: str, text: str,
             vector: list, has_yield: bool, yield_val: Optional[float]) -> dict:
    start = None
    if not na(exp.get("start_date")):
        try: start = pd.to_datetime(exp["start_date"]).strftime("%Y-%m-%dT%H:%M:%SZ")
        except: pass
    return {
        "chunk_id":          f"{int(exp['experiment_id'])}_{chunk_type}",
        "text":              text[:MAX_CHARS],
        "embedding":         vector,
        "experiment_id":     int(exp["experiment_id"]),
        "exp_number_full":   str(exp["exp_number_full"]) if not na(exp.get("exp_number_full")) else None,
        "experiment_title":  str(exp["title"])           if not na(exp.get("title"))           else None,
        "project_code":      str(exp["project_code"])    if not na(exp.get("project_code"))    else None,
        "team":              str(exp["team_code"])        if not na(exp.get("team_code"))        else None,
        "scientist":         None,
        "start_date":        start,
        "chunk_type":        chunk_type,
        "has_yield":         has_yield,
        "yield_value":       float(yield_val) if yield_val is not None else None,
        "experiment_status": int(exp["experiment_status"]) if not na(exp.get("experiment_status")) else None,
    }


def process(exp: pd.Series, data: dict, oai: AzureOpenAI) -> list:
    eid   = int(exp["experiment_id"])
    proc  = data["eln_experiment_procedure"]
    steps = proc[proc["experiment_id"] == eid]
    if "step_order" in steps.columns: steps = steps.sort_values("step_order")
    mats  = data["eln_experiment_materials"][data["eln_experiment_materials"]["experiment_id"] == eid]
    prods = data["eln_experiment_products"][data["eln_experiment_products"]["experiment_id"] == eid]
    tlcs  = data["eln_experiment_tlc"][data["eln_experiment_tlc"]["experiment_id"] == eid]

    has_yield, yield_val = extract_yield(prods)
    docs = []

    ov = overview_text(exp)
    if ov.strip():
        docs.append(make_doc(exp, "overview", ov, embed(oai, ov), has_yield, yield_val))

    pv = procedure_text(steps)
    if pv.strip():
        pv = f"Procedure for {exp.get('exp_number_full', eid)}:\n{pv}"
        docs.append(make_doc(exp, "procedure", pv, embed(oai, pv), has_yield, yield_val))

    rv = results_text(mats, prods, tlcs)
    if rv.strip():
        rv = f"Results for {exp.get('exp_number_full', eid)}:\n{rv}"
        docs.append(make_doc(exp, "results", rv, embed(oai, rv), has_yield, yield_val))

    return docs


def main():
    log.info("ELN indexer starting (blob CSV mode)")
    blob, oai, search = build_clients()

    data = load_tables(blob)
    exps = build_exp_df(data)

    if EXPERIMENT_ID:
        exps = exps[exps["experiment_id"] == int(EXPERIMENT_ID)]
        log.info(f"Filtered to experiment {EXPERIMENT_ID}")

    log.info(f"Experiments to index: {len(exps)}")
    total, errors, batch = 0, 0, []

    for _, exp in exps.iterrows():
        eid = int(exp["experiment_id"])
        try:
            batch.extend(process(exp, data, oai))
            if len(batch) >= BATCH_SIZE:
                res    = search.upload_documents(documents=batch)
                ok     = sum(1 for r in res if r.succeeded)
                bad    = sum(1 for r in res if not r.succeeded)
                total += ok; errors += bad
                if bad: log.warning(f"Batch: {bad} failures")
                batch = []
                log.info(f"Progress: {total} indexed, {errors} errors")
        except Exception as e:
            errors += 1
            log.error(f"Experiment {eid} failed: {e}", exc_info=True)

    if batch:
        res    = search.upload_documents(documents=batch)
        total += sum(1 for r in res if r.succeeded)
        errors += sum(1 for r in res if not r.succeeded)

    log.info(f"Done: {total} indexed, {errors} errors")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
