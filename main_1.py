"""
main.py — Covvalent ELN Intelligence Platform API v2.1.0
Adds experiment drill-down endpoints from Atlas DB.
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List
import pyodbc, os, logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = FastAPI(
    title="Covvalent ELN Intelligence API",
    version="2.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SQL_SERVER   = os.getenv("SQL_SERVER",   "10.0.0.4,1433")
SQL_DATABASE = os.getenv("SQL_DATABASE", "ELNAnalytics")
SQL_USERNAME = os.getenv("SQL_USERNAME", "eln_reader")
SQL_PASSWORD = os.getenv("SQL_PASSWORD", "")

EXP_STATUS = {1:"Draft", 2:"Under Review", 3:"Approved", 4:"Locked",
              5:"Completed", 6:"Abandoned"}


def get_conn():
    return pyodbc.connect(
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={SQL_SERVER};DATABASE={SQL_DATABASE};"
        f"UID={SQL_USERNAME};PWD={SQL_PASSWORD};"
        "TrustServerCertificate=yes;Connection Timeout=10;"
    )


def rows_to_dicts(cursor):
    cols = [c[0] for c in cursor.description]
    return [
        {k: (v.isoformat() if isinstance(v, datetime) else v)
         for k, v in zip(cols, row)}
        for row in cursor.fetchall()
    ]


# ── Health ────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "healthy", "service": "eln-api-covvalent",
            "version": "2.1.0", "timestamp": datetime.utcnow().isoformat()}


@app.get("/health/sql")
def health_sql():
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("""
            SELECT
                (SELECT COUNT(*) FROM dbo.eln_projects)            AS projects,
                (SELECT COUNT(*) FROM dbo.eln_project_teams)       AS teams,
                (SELECT COUNT(*) FROM dbo.eln_requests)            AS requests,
                (SELECT COUNT(*) FROM dbo.eln_requested_materials) AS materials,
                (SELECT COUNT(*) FROM dbo.eln_experiments)         AS experiments,
                (SELECT COUNT(*) FROM dbo.eln_experiment_materials) AS exp_materials,
                (SELECT COUNT(*) FROM dbo.eln_experiment_products) AS exp_products,
                (SELECT COUNT(*) FROM dbo.eln_experiment_tlc)      AS exp_tlc,
                (SELECT MAX(run_started_at) FROM dbo.eln_etl_log
                 WHERE status='success')                            AS last_etl_run
        """)
        row = cur.fetchone(); conn.close()
        return {
            "status": "ok", "database": SQL_DATABASE, "server": SQL_SERVER,
            "counts": {
                "projects": row[0], "teams": row[1], "requests": row[2],
                "materials": row[3], "experiments": row[4],
                "exp_materials": row[5], "exp_products": row[6],
                "exp_tlc": row[7],
            },
            "last_etl_run": row[8].isoformat() if row[8] else None,
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# ── Projects ──────────────────────────────────────────────────────────
@app.get("/api/projects")
def get_projects(
    status: Optional[int] = Query(None),
    is_rm:  Optional[bool] = Query(None),
):
    try:
        conn = get_conn(); cur = conn.cursor()
        sql = """
            SELECT p.project_id, p.project_code, p.title, p.generic_name,
                p.cas_number, p.iupac_name, p.start_date, p.end_date,
                p.project_status, p.is_rm_project, p.primary_project_type,
                p.created_date, p.etl_synced_at,
                COUNT(DISTINCT pt.project_team_id) AS team_count,
                COUNT(DISTINCT r.request_id)        AS request_count,
                COUNT(DISTINCT e.experiment_id)     AS experiment_count
            FROM dbo.eln_projects p
            LEFT JOIN dbo.eln_project_teams pt ON p.project_id = pt.project_id
            LEFT JOIN dbo.eln_requests r ON pt.project_team_id = r.project_team_id
            LEFT JOIN dbo.eln_experiments e ON pt.project_team_id = e.project_team_id
            WHERE 1=1
        """
        params = []
        if status is not None:
            sql += " AND p.project_status = ?"; params.append(status)
        if is_rm is not None:
            sql += " AND p.is_rm_project = ?"; params.append(1 if is_rm else 0)
        sql += """ GROUP BY p.project_id, p.project_code, p.title, p.generic_name,
            p.cas_number, p.iupac_name, p.start_date, p.end_date,
            p.project_status, p.is_rm_project, p.primary_project_type,
            p.created_date, p.etl_synced_at ORDER BY p.start_date DESC"""
        cur.execute(sql, params)
        data = rows_to_dicts(cur); conn.close()
        return {"count": len(data), "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projects/{project_id}")
def get_project(project_id: int):
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT * FROM dbo.eln_projects WHERE project_id=?", project_id)
        projects = rows_to_dicts(cur)
        if not projects:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
        cur.execute("SELECT * FROM dbo.eln_project_teams WHERE project_id=? ORDER BY start_date DESC", project_id)
        teams = rows_to_dicts(cur)
        team_ids = [t["project_team_id"] for t in teams]
        requests = []
        if team_ids:
            ph = ",".join("?"*len(team_ids))
            cur.execute(f"SELECT * FROM dbo.eln_requests WHERE project_team_id IN ({ph}) ORDER BY created_date DESC", team_ids)
            requests = rows_to_dicts(cur)
        conn.close()
        return {"project": projects[0], "teams": teams, "requests": requests}
    except HTTPException: raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Experiments ───────────────────────────────────────────────────────
@app.get("/api/projects/{project_id}/experiments")
def get_project_experiments(
    project_id: int,
    limit: int = Query(100, le=500)
):
    """All experiments for a project, across all its teams."""
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute(f"""
            SELECT TOP {limit}
                e.experiment_id,
                e.project_team_id,
                e.experiment_status,
                e.prefix,
                e.experiment_number,
                e.exp_number_full,
                e.title,
                e.objective,
                e.conclusion,
                e.start_date,
                e.end_date,
                e.is_marked_complete,
                e.created_date,
                e.updated_date,
                pt.team_code,
                p.project_code,
                p.title AS project_title,
                (SELECT COUNT(*) FROM dbo.eln_experiment_materials em
                 WHERE em.experiment_id = e.experiment_id) AS material_count,
                (SELECT COUNT(*) FROM dbo.eln_experiment_products ep
                 WHERE ep.experiment_id = e.experiment_id) AS product_count
            FROM dbo.eln_experiments e
            JOIN dbo.eln_project_teams pt ON e.project_team_id = pt.project_team_id
            JOIN dbo.eln_projects p ON pt.project_id = p.project_id
            WHERE p.project_id = ?
            AND e.is_active = 1
            ORDER BY e.experiment_id DESC
        """, project_id)
        data = rows_to_dicts(cur); conn.close()
        return {"project_id": project_id, "count": len(data), "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/experiments")
def get_experiments(
    project_team_id: Optional[int] = Query(None),
    status:          Optional[int] = Query(None),
    limit:           int           = Query(50, le=200)
):
    try:
        conn = get_conn(); cur = conn.cursor()
        sql = f"""
            SELECT TOP {limit}
                e.experiment_id, e.project_team_id, e.experiment_status,
                e.prefix, e.experiment_number, e.exp_number_full,
                e.title, e.start_date, e.end_date,
                e.is_marked_complete, e.created_date, e.updated_date,
                pt.team_code, p.project_code, p.title AS project_title,
                p.cas_number AS project_cas
            FROM dbo.eln_experiments e
            JOIN dbo.eln_project_teams pt ON e.project_team_id = pt.project_team_id
            JOIN dbo.eln_projects p ON pt.project_id = p.project_id
            WHERE e.is_active = 1
        """
        params = []
        if project_team_id:
            sql += " AND e.project_team_id=?"; params.append(project_team_id)
        if status:
            sql += " AND e.experiment_status=?"; params.append(status)
        sql += " ORDER BY e.experiment_id DESC"
        cur.execute(sql, params)
        data = rows_to_dicts(cur); conn.close()
        return {"count": len(data), "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/experiments/{experiment_id}")
def get_experiment(experiment_id: int):
    """Full experiment detail: metadata + sections + raw materials + products + TLC."""
    try:
        conn = get_conn(); cur = conn.cursor()

        # Experiment header
        cur.execute("""
            SELECT e.*, pt.team_code, p.project_code, p.title AS project_title,
                p.cas_number AS project_cas
            FROM dbo.eln_experiments e
            JOIN dbo.eln_project_teams pt ON e.project_team_id = pt.project_team_id
            JOIN dbo.eln_projects p ON pt.project_id = p.project_id
            WHERE e.experiment_id = ?
        """, experiment_id)
        experiments = rows_to_dicts(cur)
        if not experiments:
            raise HTTPException(status_code=404, detail=f"Experiment {experiment_id} not found")
        experiment = experiments[0]

        # Sections
        cur.execute("""
            SELECT section_id, section_type_id, section_title, section_order
            FROM dbo.eln_experiment_sections
            WHERE experiment_id = ? AND is_active = 1
            ORDER BY section_order
        """, experiment_id)
        sections = rows_to_dicts(cur)

        # Raw materials
        cur.execute("""
            SELECT raw_material_id, raw_material_name, cas_number,
                molecular_formula, quantity, unit, purity, batch,
                moles, ratio, is_limiting_agent, remarks
            FROM dbo.eln_experiment_materials
            WHERE experiment_id = ? AND is_active = 1
            ORDER BY is_limiting_agent DESC, raw_material_id
        """, experiment_id)
        raw_materials = rows_to_dicts(cur)

        # Products
        cur.execute("""
            SELECT reaction_product_id, product_name, molecular_formula,
                molecular_weight, iupac_name, dry_wt, crude_yield,
                purified_yield, purity, theoretical_crude_yield,
                atom_economy, e_factor_actual
            FROM dbo.eln_experiment_products
            WHERE experiment_id = ? AND is_active = 1
        """, experiment_id)
        products = rows_to_dicts(cur)

        # TLC
        cur.execute("""
            SELECT tlc_plate_id, plate_title, plate_notes,
                spot_a_notes, rf1, spot_b_notes, rf2,
                spot_c_notes, rf3, spot_d_notes, rf4
            FROM dbo.eln_experiment_tlc
            WHERE experiment_id = ? AND is_active = 1
        """, experiment_id)
        tlc = rows_to_dicts(cur)

        conn.close()
        return {
            "experiment":   experiment,
            "sections":     sections,
            "raw_materials": raw_materials,
            "products":     products,
            "tlc":          tlc,
        }
    except HTTPException: raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Teams ─────────────────────────────────────────────────────────────
@app.get("/api/teams")
def get_teams(project_id: Optional[int] = Query(None)):
    try:
        conn = get_conn(); cur = conn.cursor()
        sql = """
            SELECT pt.*, p.project_code, p.title AS project_title, p.cas_number,
                COUNT(DISTINCT r.request_id) AS request_count,
                COUNT(DISTINCT e.experiment_id) AS experiment_count
            FROM dbo.eln_project_teams pt
            JOIN dbo.eln_projects p ON pt.project_id = p.project_id
            LEFT JOIN dbo.eln_requests r ON pt.project_team_id = r.project_team_id
            LEFT JOIN dbo.eln_experiments e ON pt.project_team_id = e.project_team_id
            WHERE pt.is_active = 1
        """
        params = []
        if project_id:
            sql += " AND pt.project_id=?"; params.append(project_id)
        sql += """ GROUP BY pt.project_team_id, pt.project_id, pt.team_code,
            pt.department_id, pt.start_date, pt.end_date, pt.project_status,
            pt.conclusion, pt.remarks, pt.next_action_plan, pt.total_budget,
            pt.label_claim, pt.label_claim_unit, pt.is_rm_project_team,
            pt.is_active, pt.created_date, pt.updated_date, pt.etl_synced_at,
            p.project_code, p.title, p.cas_number ORDER BY pt.start_date DESC"""
        cur.execute(sql, params)
        data = rows_to_dicts(cur); conn.close()
        return {"count": len(data), "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Requests ──────────────────────────────────────────────────────────
@app.get("/api/requests")
def get_requests(
    project_team_id: Optional[int] = Query(None),
    status:          Optional[int] = Query(None),
    limit:           int           = Query(100, le=500),
):
    try:
        conn = get_conn(); cur = conn.cursor()
        sql = f"""
            SELECT TOP {limit}
                r.*, pt.team_code, p.project_code, p.title AS project_title,
                COUNT(rm.material_request_id) AS material_count
            FROM dbo.eln_requests r
            LEFT JOIN dbo.eln_project_teams pt ON r.project_team_id = pt.project_team_id
            LEFT JOIN dbo.eln_projects p ON pt.project_id = p.project_id
            LEFT JOIN dbo.eln_requested_materials rm ON r.request_id = rm.request_id
            WHERE r.is_active = 1
        """
        params = []
        if project_team_id:
            sql += " AND r.project_team_id=?"; params.append(project_team_id)
        if status:
            sql += " AND r.request_status=?"; params.append(status)
        sql += """ GROUP BY r.request_id, r.request_number, r.request_status,
            r.project_team_id, r.notes, r.is_active, r.created_date,
            r.updated_date, r.etl_synced_at, pt.team_code, p.project_code,
            p.title ORDER BY r.created_date DESC"""
        cur.execute(sql, params)
        data = rows_to_dicts(cur); conn.close()
        return {"count": len(data), "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/requests/{request_id}")
def get_request(request_id: int):
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT * FROM dbo.eln_requests WHERE request_id=?", request_id)
        requests = rows_to_dicts(cur)
        if not requests:
            raise HTTPException(status_code=404, detail=f"Request {request_id} not found")
        cur.execute("""
            SELECT * FROM dbo.eln_requested_materials
            WHERE request_id=? AND is_active=1 ORDER BY created_date
        """, request_id)
        materials = rows_to_dicts(cur); conn.close()
        return {"request": requests[0], "materials": materials}
    except HTTPException: raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Materials ─────────────────────────────────────────────────────────
@app.get("/api/materials")
def get_materials(
    request_id: Optional[int] = Query(None),
    cas_number: Optional[str] = Query(None),
    limit:      int           = Query(200, le=1000),
):
    try:
        conn = get_conn(); cur = conn.cursor()
        sql = f"""
            SELECT TOP {limit} rm.*, r.request_number, pt.team_code,
                p.project_code, p.title AS project_title
            FROM dbo.eln_requested_materials rm
            JOIN dbo.eln_requests r ON rm.request_id = r.request_id
            LEFT JOIN dbo.eln_project_teams pt ON r.project_team_id = pt.project_team_id
            LEFT JOIN dbo.eln_projects p ON pt.project_id = p.project_id
            WHERE rm.is_active = 1
        """
        params = []
        if request_id:
            sql += " AND rm.request_id=?"; params.append(request_id)
        if cas_number:
            sql += " AND rm.cas_number=?"; params.append(cas_number)
        sql += " ORDER BY rm.created_date DESC"
        cur.execute(sql, params)
        data = rows_to_dicts(cur); conn.close()
        return {"count": len(data), "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Dashboard summary ─────────────────────────────────────────────────
@app.get("/api/dashboard/summary")
def get_summary():
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("""
            SELECT
                (SELECT COUNT(*) FROM dbo.eln_projects WHERE project_status=1)       AS active_projects,
                (SELECT COUNT(*) FROM dbo.eln_projects)                              AS total_projects,
                (SELECT COUNT(*) FROM dbo.eln_project_teams WHERE is_active=1)       AS active_teams,
                (SELECT COUNT(*) FROM dbo.eln_requests WHERE is_active=1)            AS total_requests,
                (SELECT COUNT(*) FROM dbo.eln_requested_materials WHERE is_active=1) AS total_materials,
                (SELECT COUNT(DISTINCT cas_number)
                 FROM dbo.eln_requested_materials
                 WHERE cas_number IS NOT NULL AND is_active=1)                        AS unique_compounds,
                (SELECT COUNT(*) FROM dbo.eln_projects WHERE is_rm_project=1)        AS rm_projects,
                (SELECT COUNT(*) FROM dbo.eln_experiments WHERE is_active=1)         AS total_experiments,
                (SELECT COUNT(*) FROM dbo.eln_experiments
                 WHERE experiment_status=1 AND is_active=1)                          AS draft_experiments,
                (SELECT COUNT(*) FROM dbo.eln_experiments
                 WHERE experiment_status=5 AND is_active=1)                          AS completed_experiments,
                (SELECT MAX(etl_synced_at) FROM dbo.eln_projects)                    AS last_sync
        """)
        row = cur.fetchone()

        cur.execute("""
            SELECT TOP 5 project_id, project_code, title, cas_number,
                start_date, project_status
            FROM dbo.eln_projects ORDER BY start_date DESC
        """)
        recent = rows_to_dicts(cur)

        cur.execute("""
            SELECT TOP 10 material_name, cas_number,
                COUNT(*) AS usage_count, SUM(quantity) AS total_quantity
            FROM dbo.eln_requested_materials
            WHERE is_active=1 AND material_name IS NOT NULL
            GROUP BY material_name, cas_number
            ORDER BY usage_count DESC
        """)
        top_materials = rows_to_dicts(cur)

        cur.execute("""
            SELECT TOP 5 e.experiment_id, e.exp_number_full, e.title,
                e.experiment_status, e.start_date, p.project_code
            FROM dbo.eln_experiments e
            JOIN dbo.eln_project_teams pt ON e.project_team_id = pt.project_team_id
            JOIN dbo.eln_projects p ON pt.project_id = p.project_id
            WHERE e.is_active=1
            ORDER BY e.experiment_id DESC
        """)
        recent_experiments = rows_to_dicts(cur)

        conn.close()
        return {
            "summary": {
                "active_projects":      row[0],
                "total_projects":       row[1],
                "active_teams":         row[2],
                "total_requests":       row[3],
                "total_materials":      row[4],
                "unique_compounds":     row[5],
                "rm_projects":          row[6],
                "total_experiments":    row[7],
                "draft_experiments":    row[8],
                "completed_experiments": row[9],
                "last_sync": row[10].isoformat() if row[10] else None,
            },
            "recent_projects":     recent,
            "top_materials":       top_materials,
            "recent_experiments":  recent_experiments,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── ETL status ────────────────────────────────────────────────────────
@app.get("/api/etl/status")
def get_etl_status(limit: int = Query(10, le=50)):
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute(f"""
            SELECT TOP {limit} log_id, run_started_at, run_finished_at, status,
                projects_upserted, teams_upserted, requests_upserted,
                materials_upserted, error_message,
                DATEDIFF(second, run_started_at, run_finished_at) AS duration_seconds
            FROM dbo.eln_etl_log ORDER BY run_started_at DESC
        """)
        data = rows_to_dicts(cur); conn.close()
        return {"count": len(data), "runs": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
