"""
routers/fetch.py — Tool 1: Structured SQL retrieval
POST /api/ai/fetch
Supports: project_code, experiment_id, exp_number_full,
          days, cas_number, product_name, chemistry (all optional)
"""

import os
import pyodbc
from datetime import datetime, date
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter()

def get_conn():
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

def rows_to_dicts(cursor):
    cols = [c[0] for c in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]

def serialize(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return obj

def clean(rows):
    return [{k: serialize(v) for k, v in row.items()} for row in rows]

def get_experiment_detail(cur, exp_id):
    """Fetch full detail for a single experiment_id."""
    cur.execute("""
        SELECT e.experiment_id, e.exp_number_full, e.title,
               e.author, e.created_date, e.experiment_status,
               e.objective, e.conclusion, e.next_action_plan,
               p.project_code, p.title AS project_title,
               p.cas_number, p.generic_name, p.iupac_name
        FROM eln_experiments e
        LEFT JOIN eln_project_teams pt ON e.project_team_id = pt.project_team_id
        LEFT JOIN eln_projects p ON pt.project_id = p.project_id
        WHERE e.experiment_id = ?
    """, exp_id)
    row = cur.fetchone()
    if not row:
        return None
    cols   = [c[0] for c in cur.description]
    result = {k: serialize(v) for k, v in zip(cols, row)}

    cur.execute("""
        SELECT raw_material_name, cas_number, quantity, unit,
               moles, ratio, is_limiting_agent
        FROM eln_experiment_materials
        WHERE experiment_id = ? AND is_active = 1
        ORDER BY raw_material_id
    """, exp_id)
    result["materials"] = clean(rows_to_dicts(cur))

    cur.execute("""
        SELECT product_name, dry_wt, crude_yield, purified_yield,
               purity, atom_economy, e_factor_actual
        FROM eln_experiment_products
        WHERE experiment_id = ? AND is_active = 1
        ORDER BY reaction_product_id
    """, exp_id)
    result["products"] = clean(rows_to_dicts(cur))

    cur.execute("""
        SELECT step_order, operation, quantity, temperature,
               time_value, observations
        FROM eln_experiment_procedure
        WHERE experiment_id = ? AND is_active = 1 AND is_header = 0
        ORDER BY step_order
    """, exp_id)
    result["procedure"] = clean(rows_to_dicts(cur))

    cur.execute("""
        SELECT plate_title, plate_notes,
               spot_a_notes, rf1, spot_b_notes, rf2,
               spot_c_notes, rf3, spot_d_notes, rf4
        FROM eln_experiment_tlc
        WHERE experiment_id = ? AND is_active = 1
        ORDER BY tlc_plate_id
    """, exp_id)
    result["tlc"] = clean(rows_to_dicts(cur))

    return result


class FetchRequest(BaseModel):
    # Single experiment lookup
    project_code:    Optional[str] = None
    experiment_id:   Optional[int] = None
    exp_number_full: Optional[str] = None
    # Date-range filter
    days:            Optional[int] = None   # e.g. 7 = last 7 days
    # Chemistry/product filters
    cas_number:      Optional[str] = None   # find projects by CAS
    product_name:    Optional[str] = None   # fuzzy match on product/project name
    chemistry:       Optional[str] = None   # reaction class / reagent keyword
    # Pagination
    limit:           Optional[int] = 50
    offset:          Optional[int] = 0


@router.post("/api/ai/fetch")
def fetch(req: FetchRequest):
    try:
        conn = get_conn()
        cur  = conn.cursor()

        # ── Mode 1: Empty body — return all projects ──────────────────────────
        if not any([req.project_code, req.experiment_id, req.exp_number_full,
                    req.days, req.cas_number, req.product_name, req.chemistry]):
            cur.execute("""
                SELECT project_id, project_code,
                       title AS project_title, cas_number,
                       generic_name, iupac_name, project_status, start_date
                FROM eln_projects
                ORDER BY project_code
            """)
            projects = clean(rows_to_dicts(cur))
            conn.close()
            return {"type": "project_list", "count": len(projects), "projects": projects}

        # ── Mode 2: Single experiment by ID or exp_number_full ────────────────
        if req.experiment_id:
            result = get_experiment_detail(cur, req.experiment_id)
            conn.close()
            if not result:
                raise HTTPException(404, detail="Experiment not found")
            return {"type": "experiment", **result}

        if req.exp_number_full and not req.project_code:
            cur.execute("SELECT experiment_id FROM eln_experiments WHERE exp_number_full = ?",
                       req.exp_number_full)
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, detail=f"Experiment {req.exp_number_full} not found")
            result = get_experiment_detail(cur, row[0])
            conn.close()
            return {"type": "experiment", **result}

        # ── Mode 3: Project drill-down (no other filters) ─────────────────────
        if req.project_code and not any([req.days, req.chemistry]):
            cur.execute("""
                SELECT project_id, project_code,
                       title AS project_title, cas_number,
                       generic_name, iupac_name, project_status, start_date
                FROM eln_projects WHERE project_code = ?
            """, req.project_code)
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, detail=f"Project {req.project_code} not found")
            cols    = [c[0] for c in cur.description]
            project = {k: serialize(v) for k, v in zip(cols, row)}

            cur.execute("""
                SELECT e.experiment_id, e.exp_number_full, e.title,
                       e.author, e.created_date, e.experiment_status
                FROM eln_experiments e
                JOIN eln_project_teams pt ON e.project_team_id = pt.project_team_id
                JOIN eln_projects p ON pt.project_id = p.project_id
                WHERE p.project_code = ?
                ORDER BY e.created_date DESC
            """, req.project_code)
            experiments = clean(rows_to_dicts(cur))
            conn.close()
            return {"type": "project", "project": project,
                    "experiments": experiments, "count": len(experiments)}

        # ── Mode 4: Date-range filter ─────────────────────────────────────────
        if req.days and not req.chemistry:
            where_clauses = ["e.created_date >= DATEADD(day, ?, GETDATE())"]
            params = [-req.days]

            if req.project_code:
                where_clauses.append("p.project_code = ?")
                params.append(req.project_code)

            where = "WHERE " + " AND ".join(where_clauses)
            params += [req.offset, req.limit]

            cur.execute(f"""
                SELECT e.experiment_id, e.exp_number_full, e.title,
                       e.author, e.created_date, e.experiment_status,
                       e.objective, e.conclusion,
                       p.project_code, p.title AS project_title,
                       p.cas_number, p.generic_name
                FROM eln_experiments e
                JOIN eln_project_teams pt ON e.project_team_id = pt.project_team_id
                JOIN eln_projects p ON pt.project_id = p.project_id
                {where}
                ORDER BY e.created_date DESC
                OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
            """, params)
            experiments = clean(rows_to_dicts(cur))

            # Count
            cur.execute(f"""
                SELECT COUNT(*)
                FROM eln_experiments e
                JOIN eln_project_teams pt ON e.project_team_id = pt.project_team_id
                JOIN eln_projects p ON pt.project_id = p.project_id
                {where.replace('OFFSET ? ROWS FETCH NEXT ? ROWS ONLY', '')}
            """, params[:-2])
            total = cur.fetchone()[0]

            conn.close()
            return {
                "type":        "date_range",
                "days":        req.days,
                "project_code": req.project_code,
                "total":       total,
                "count":       len(experiments),
                "experiments": experiments
            }

        # ── Mode 5: CAS number lookup ─────────────────────────────────────────
        if req.cas_number:
            cur.execute("""
                SELECT project_id, project_code,
                       title AS project_title, cas_number,
                       generic_name, iupac_name, project_status
                FROM eln_projects
                WHERE cas_number = ?
            """, req.cas_number)
            projects = clean(rows_to_dicts(cur))
            if not projects:
                conn.close()
                return {"type": "cas_lookup", "cas_number": req.cas_number,
                        "count": 0, "projects": [],
                        "message": f"No project found with CAS {req.cas_number}"}

            # Get experiments for matching projects
            result_projects = []
            for p in projects:
                cur.execute("""
                    SELECT e.experiment_id, e.exp_number_full, e.title,
                           e.author, e.created_date, e.experiment_status
                    FROM eln_experiments e
                    JOIN eln_project_teams pt ON e.project_team_id = pt.project_team_id
                    WHERE pt.project_id = ?
                    ORDER BY e.created_date DESC
                """, p["project_id"])
                p["experiments"] = clean(rows_to_dicts(cur))
                p["experiment_count"] = len(p["experiments"])
                result_projects.append(p)

            conn.close()
            return {"type": "cas_lookup", "cas_number": req.cas_number,
                    "count": len(result_projects), "projects": result_projects}

        # ── Mode 6: Product name fuzzy search ─────────────────────────────────
        if req.product_name and not req.chemistry:
            keyword = f"%{req.product_name}%"
            cur.execute("""
                SELECT DISTINCT p.project_id, p.project_code,
                       p.title AS project_title, p.cas_number,
                       p.generic_name, p.iupac_name, p.project_status
                FROM eln_projects p
                WHERE p.title LIKE ?
                   OR p.generic_name LIKE ?
                   OR p.iupac_name LIKE ?
                   OR p.cas_number LIKE ?
                ORDER BY p.project_code
            """, keyword, keyword, keyword, keyword)
            projects = clean(rows_to_dicts(cur))

            # Also search in experiment products
            cur.execute("""
                SELECT DISTINCT p.project_id, p.project_code,
                       p.title AS project_title, p.cas_number, p.generic_name
                FROM eln_experiment_products ep
                JOIN eln_experiments e ON ep.experiment_id = e.experiment_id
                JOIN eln_project_teams pt ON e.project_team_id = pt.project_team_id
                JOIN eln_projects p ON pt.project_id = p.project_id
                WHERE ep.product_name LIKE ?
                ORDER BY p.project_code
            """, keyword)
            product_matches = clean(rows_to_dicts(cur))

            # Merge deduplicated
            seen = {p["project_code"] for p in projects}
            for pm in product_matches:
                if pm["project_code"] not in seen:
                    projects.append(pm)
                    seen.add(pm["project_code"])

            conn.close()
            return {"type": "product_name_search", "keyword": req.product_name,
                    "count": len(projects), "projects": projects}

        # ── Mode 7: Chemistry / reaction class search ─────────────────────────
        if req.chemistry:
            keyword = f"%{req.chemistry}%"
            where_clauses = []
            params = []

            if req.project_code:
                where_clauses.append("p.project_code = ?")
                params.append(req.project_code)

            if req.days:
                where_clauses.append("e.created_date >= DATEADD(day, ?, GETDATE())")
                params.append(-req.days)

            project_filter = ("AND " + " AND ".join(where_clauses)) if where_clauses else ""

            # Search across: objective, conclusion, procedure observations, material names
            cur.execute(f"""
                SELECT DISTINCT
                    e.experiment_id, e.exp_number_full, e.title,
                    e.author, e.created_date, e.experiment_status,
                    e.objective, e.conclusion,
                    p.project_code, p.title AS project_title,
                    p.cas_number, p.generic_name,
                    'objective_conclusion' AS match_source
                FROM eln_experiments e
                JOIN eln_project_teams pt ON e.project_team_id = pt.project_team_id
                JOIN eln_projects p ON pt.project_id = p.project_id
                WHERE (e.objective LIKE ? OR e.conclusion LIKE ?)
                {project_filter}

                UNION

                SELECT DISTINCT
                    e.experiment_id, e.exp_number_full, e.title,
                    e.author, e.created_date, e.experiment_status,
                    e.objective, e.conclusion,
                    p.project_code, p.title AS project_title,
                    p.cas_number, p.generic_name,
                    'procedure' AS match_source
                FROM eln_experiment_procedure pr
                JOIN eln_experiments e ON pr.experiment_id = e.experiment_id
                JOIN eln_project_teams pt ON e.project_team_id = pt.project_team_id
                JOIN eln_projects p ON pt.project_id = p.project_id
                WHERE (pr.operation LIKE ? OR pr.observations LIKE ?)
                {project_filter}

                UNION

                SELECT DISTINCT
                    e.experiment_id, e.exp_number_full, e.title,
                    e.author, e.created_date, e.experiment_status,
                    e.objective, e.conclusion,
                    p.project_code, p.title AS project_title,
                    p.cas_number, p.generic_name,
                    'materials' AS match_source
                FROM eln_experiment_materials m
                JOIN eln_experiments e ON m.experiment_id = e.experiment_id
                JOIN eln_project_teams pt ON e.project_team_id = pt.project_team_id
                JOIN eln_projects p ON pt.project_id = p.project_id
                WHERE m.raw_material_name LIKE ?
                {project_filter}

                ORDER BY created_date DESC
                OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
            """,
            keyword, keyword,   # objective/conclusion
            *params,
            keyword, keyword,   # procedure
            *params,
            keyword,            # materials
            *params,
            req.offset, req.limit
            )
            experiments = clean(rows_to_dicts(cur))

            conn.close()
            return {
                "type":        "chemistry_search",
                "chemistry":   req.chemistry,
                "project_code": req.project_code,
                "days":        req.days,
                "count":       len(experiments),
                "experiments": experiments,
                "note":        f"Matched '{req.chemistry}' in objective, conclusion, procedure steps, and material names. Use fetch_experiment with experiment_id for full detail on any entry."
            }

        conn.close()
        raise HTTPException(400, detail="No valid query parameters provided")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, detail=str(e))


# ── Direct CSV export endpoint ────────────────────────────────────────────────
from fastapi.responses import StreamingResponse
import csv, io

class ExportRequest(BaseModel):
    days:         Optional[int]  = None
    from_date:    Optional[str]  = None   # ISO date string e.g. "2026-04-01"
    to_date:      Optional[str]  = None   # ISO date string e.g. "2026-06-30"
    project_code: Optional[str]  = None
    author:       Optional[str]  = None
    cas_number:   Optional[str]  = None

@router.post("/api/ai/export")
def export_csv(req: ExportRequest):
    """Direct CSV export — bypasses agent, returns full untruncated dataset."""
    try:
        conn = get_conn()
        cur  = conn.cursor()

        where_clauses = []
        params = []

        if req.from_date:
            where_clauses.append("e.created_date >= ?")
            params.append(req.from_date)
        if req.to_date:
            where_clauses.append("e.created_date <= ?")
            params.append(req.to_date + " 23:59:59")
        if req.days and not req.from_date:
            where_clauses.append("e.created_date >= DATEADD(day, ?, GETDATE())")
            params.append(-req.days)
        if req.project_code:
            where_clauses.append("p.project_code = ?")
            params.append(req.project_code)
        if req.author:
            where_clauses.append("e.author LIKE ?")
            params.append(f"%{req.author}%")
        if req.cas_number:
            where_clauses.append("p.cas_number = ?")
            params.append(req.cas_number)

        where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        cur.execute(f"""
            SELECT
                e.exp_number_full,
                CONVERT(VARCHAR(19), e.created_date, 120) AS created_date,
                e.author,
                p.project_code,
                p.title AS project_title,
                p.generic_name,
                p.cas_number,
                e.title AS experiment_title,
                e.objective,
                e.conclusion,
                CASE e.experiment_status
                    WHEN 1 THEN 'In Progress'
                    WHEN 2 THEN 'Submitted'
                    WHEN 3 THEN 'Approved'
                    WHEN 4 THEN 'Rejected'
                    WHEN 5 THEN 'Closed'
                    WHEN 6 THEN 'Archived'
                    ELSE CAST(e.experiment_status AS VARCHAR)
                END AS experiment_status
            FROM eln_experiments e
            JOIN eln_project_teams pt ON e.project_team_id = pt.project_team_id
            JOIN eln_projects p ON pt.project_id = p.project_id
            {where}
            ORDER BY e.created_date DESC
        """, params)

        rows = cur.fetchall()
        cols = [c[0] for c in cur.description]
        conn.close()

        # Stream as CSV
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(cols)
        for row in rows:
            writer.writerow(['' if v is None else v for v in row])

        output.seek(0)
        filename = f"eln-export-{req.days or 'all'}d.csv"
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}",
                     "Access-Control-Expose-Headers": "Content-Disposition"}
        )

    except Exception as e:
        raise HTTPException(500, detail=str(e))
