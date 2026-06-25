# Procedure endpoint to add to main.py
# Add this function AFTER the get_experiment() function

@app.get("/api/experiments/{experiment_id}/procedure")
def get_experiment_procedure(experiment_id: int):
    """Step-by-step procedure for an experiment."""
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("""
            SELECT
                procedure_row_id, step_order, is_header,
                step_date, operation, quantity, time_value,
                temperature, observations
            FROM dbo.eln_experiment_procedure
            WHERE experiment_id = ?
            AND is_active = 1
            AND is_header = 0
            AND operation IS NOT NULL
            ORDER BY step_order
        """, experiment_id)
        steps = rows_to_dicts(cur)
        conn.close()
        return {"experiment_id": experiment_id, "step_count": len(steps), "steps": steps}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
