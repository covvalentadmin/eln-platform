"""
main.py — Covvalent ELN Intelligence Platform FastAPI v2.3.0
"""

import os
from datetime import datetime, date
from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import pyodbc

from routers import search, fetch, agent, literature, report, meeting, upload

app = FastAPI(title="ELN Intelligence API", version="2.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(search.router)
app.include_router(fetch.router)
app.include_router(agent.router)
app.include_router(literature.router)
app.include_router(report.router)
app.include_router(meeting.router)
app.include_router(upload.router)

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

# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "version": "2.3.0"}

@app.get("/health/sql")
def health_sql():
    try:
        conn = get_conn()
        cur = conn.cursor()
        counts = {}
        for tbl in ["eln_projects","eln_experiments","eln_experiment_materials",
                    "eln_experiment_products","eln_experiment_tlc","eln_etl_log"]:
            cur.execute(f"SELECT COUNT(*) FROM {tbl}")
            counts[tbl] = cur.fetchone()[0]
        conn.close()
        return {"status": "ok", "counts": counts}
    except Exception as e:
        raise HTTPException(500, detail=str(e))

# ── Schema inspection (dev) ───────────────────────────────────────────────────
@app.get("/api/dev/schema/{table_name}")
def get_schema(table_name: str):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT COLUMN_NAME, DATA_TYPE, ORDINAL_POSITION
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = ?
            ORDER BY ORDINAL_POSITION
        """, table_name)
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        conn.close()
        return {"table": table_name, "columns": rows}
    except Exception as e:
        raise HTTPException(500, detail=str(e))

# ── Projects ──────────────────────────────────────────────────────────────────
@app.get("/api/projects")
def get_projects():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT project_id, project_code, title AS project_title,
                   cas_number, generic_name, iupac_name,
                   project_status, start_date
            FROM eln_projects
            ORDER BY project_code
        """)
        rows = clean(rows_to_dicts(cur))
        conn.close()
        return rows
    except Exception as e:
        raise HTTPException(500, detail=str(e))

@app.get("/api/projects/{project_id}")
def get_project(project_id: int):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT project_id, project_code, title AS project_title,
                   cas_number, generic_name, iupac_name,
                   project_status, start_date
            FROM eln_projects WHERE project_id = ?
        """, project_id)
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, detail="Project not found")
        cols = [c[0] for c in cur.description]
        result = {k: serialize(v) for k, v in zip(cols, row)}
        conn.close()
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, detail=str(e))

# ── Experiments ───────────────────────────────────────────────────────────────
@app.get("/api/experiments")
def get_experiments(
    limit: int = Query(100, le=2000),
    offset: int = Query(0),
    project_code: Optional[str] = None
):
    try:
        conn = get_conn()
        cur = conn.cursor()
        where = ""
        params = []
        if project_code:
            where = "WHERE p.project_code = ?"
            params.append(project_code)
        cur.execute(f"""
            SELECT e.experiment_id, e.exp_number_full, e.title,
                   e.author, e.created_date, e.experiment_status,
                   p.project_code, p.title AS project_title
            FROM eln_experiments e
            LEFT JOIN eln_project_teams pt ON e.project_team_id = pt.project_team_id
            LEFT JOIN eln_projects p ON pt.project_id = p.project_id
            {where}
            ORDER BY e.created_date DESC
            OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
        """, params + [offset, limit])
        rows = clean(rows_to_dicts(cur))
        conn.close()
        return rows
    except Exception as e:
        raise HTTPException(500, detail=str(e))

@app.get("/api/experiments/{experiment_id}")
def get_experiment(experiment_id: int):
    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute("""
            SELECT e.experiment_id, e.exp_number_full, e.title,
                   e.author, e.created_date, e.experiment_status,
                   e.objective, e.conclusion, e.next_action_plan,
                   p.project_code, p.title AS project_title, p.cas_number
            FROM eln_experiments e
            LEFT JOIN eln_project_teams pt ON e.project_team_id = pt.project_team_id
            LEFT JOIN eln_projects p ON pt.project_id = p.project_id
            WHERE e.experiment_id = ?
        """, experiment_id)
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, detail="Experiment not found")
        cols = [c[0] for c in cur.description]
        result = {k: serialize(v) for k, v in zip(cols, row)}

        # Materials
        cur.execute("""
            SELECT raw_material_name, cas_number, quantity, unit,
                   moles, ratio, is_limiting_agent
            FROM eln_experiment_materials
            WHERE experiment_id = ? AND is_active = 1
            ORDER BY raw_material_id
        """, experiment_id)
        result["materials"] = clean(rows_to_dicts(cur))

        # Products
        cur.execute("""
            SELECT product_name, dry_wt, crude_yield, purified_yield,
                   purity, atom_economy, e_factor_actual
            FROM eln_experiment_products
            WHERE experiment_id = ? AND is_active = 1
            ORDER BY reaction_product_id
        """, experiment_id)
        result["products"] = clean(rows_to_dicts(cur))

        # Procedure
        cur.execute("""
            SELECT step_order, operation, quantity, temperature,
                   time_value, observations
            FROM eln_experiment_procedure
            WHERE experiment_id = ? AND is_active = 1 AND is_header = 0
            ORDER BY step_order
        """, experiment_id)
        result["procedure"] = clean(rows_to_dicts(cur))

        # TLC
        cur.execute("""
            SELECT plate_title, plate_notes,
                   spot_a_notes, rf1, spot_b_notes, rf2,
                   spot_c_notes, rf3, spot_d_notes, rf4
            FROM eln_experiment_tlc
            WHERE experiment_id = ? AND is_active = 1
            ORDER BY tlc_plate_id
        """, experiment_id)
        result["tlc"] = clean(rows_to_dicts(cur))

        conn.close()
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, detail=str(e))

# ── Dashboard summary ─────────────────────────────────────────────────────────
@app.get("/api/dashboard/summary")
def dashboard_summary():
    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM eln_projects")
        total_projects = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM eln_experiments")
        total_experiments = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(*) FROM eln_experiments
            WHERE created_date >= DATEADD(day, -7, GETDATE())
        """)
        new_last_7_days = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(DISTINCT pt.project_id)
            FROM eln_experiments e
            JOIN eln_project_teams pt ON e.project_team_id = pt.project_team_id
            WHERE e.created_date >= DATEADD(day, -7, GETDATE())
        """)
        active_last_7_days = cur.fetchone()[0]

        conn.close()
        return {
            "total_projects":     total_projects,
            "total_experiments":  total_experiments,
            "new_last_7_days":    new_last_7_days,
            "active_last_7_days": active_last_7_days
        }
    except Exception as e:
        raise HTTPException(500, detail=str(e))

def _shift_to_month_start(d, months_back):
    m = d.month - months_back
    y = d.year
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)

# ── Dashboard efficiency (3-period) ──────────────────────────────────────────
@app.get("/api/dashboard/efficiency")
def dashboard_efficiency():
    try:
        conn = get_conn()
        cur = conn.cursor()

        today = date.today()
        end_date         = today.replace(day=1)              # exclusive upper bound = start of current month
        last_month_start = _shift_to_month_start(end_date, 1)
        quarter_start    = _shift_to_month_start(end_date, 3)
        full_year_start  = _shift_to_month_start(end_date, 12)

        def _fmt_range(start, end):
            return f"{start:%b %Y} – {end:%b %Y}"

        def period_stats(start_date, end_date):
            cur.execute("""
                SELECT COUNT(*) FROM eln_experiments
                WHERE created_date >= ? AND created_date < ?
            """, start_date, end_date)
            experiment_count = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(DISTINCT author) FROM eln_experiments
                WHERE created_date >= ? AND created_date < ?
                  AND author IS NOT NULL AND author != ''
            """, start_date, end_date)
            active_scientists = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(DISTINCT pt.project_id)
                FROM eln_experiments e
                JOIN eln_project_teams pt ON e.project_team_id = pt.project_team_id
                WHERE e.created_date >= ? AND e.created_date < ?
            """, start_date, end_date)
            active_projects = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(*), COUNT(DISTINCT author), DATEDIFF(week, ?, ?)
                FROM eln_experiments
                WHERE created_date >= ? AND created_date < ?
                  AND author IS NOT NULL AND author != ''
            """, start_date, end_date, start_date, end_date)
            row = cur.fetchone()
            exp_c, sci_c, weeks = row
            avg = round(exp_c / (sci_c * max(weeks, 1)), 2) if sci_c > 0 else 0

            return {
                "experiment_count":           experiment_count,
                "active_scientists":          active_scientists,
                "active_projects":            active_projects,
                "avg_exp_per_sci_per_week":   avg,
            }

        result = {
            "last_full_year": {"label": "Last Full Year",
                               "period": _fmt_range(full_year_start, last_month_start),
                               **period_stats(full_year_start.isoformat(), end_date.isoformat())},
            "last_quarter":   {"label": "Last Quarter",
                               "period": _fmt_range(quarter_start, last_month_start),
                               **period_stats(quarter_start.isoformat(), end_date.isoformat())},
            "last_month":     {"label": "Last Month",
                               "period": f"{last_month_start:%b %Y}",
                               **period_stats(last_month_start.isoformat(), end_date.isoformat())},
        }
        conn.close()
        return result
    except Exception as e:
        raise HTTPException(500, detail=str(e))

# ── ETL status ────────────────────────────────────────────────────────────────
@app.get("/api/etl/status")
def etl_status():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT TOP 10 run_date, status, rows_inserted,
                   rows_updated, error_message
            FROM eln_etl_log
            ORDER BY run_date DESC
        """)
        rows = clean(rows_to_dicts(cur))
        conn.close()
        return rows
    except Exception as e:
        raise HTTPException(500, detail=str(e))

@app.get("/api/teams")
def get_teams():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM eln_project_teams ORDER BY project_team_id")
        rows = clean(rows_to_dicts(cur))
        conn.close()
        return rows
    except Exception as e:
        raise HTTPException(500, detail=str(e))

@app.get("/api/materials")
def get_materials():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT TOP 500 * FROM eln_experiment_materials ORDER BY raw_material_id DESC")
        rows = clean(rows_to_dicts(cur))
        conn.close()
        return rows
    except Exception as e:
        raise HTTPException(500, detail=str(e))
