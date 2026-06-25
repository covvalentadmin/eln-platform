/*
  eln_etl_v3_procedure.sql
  Adds eln_experiment_procedure table and syncs procedure steps from Atlas.
  Run after eln_etl_v2_patch.sql has already been applied.
*/

USE ELNAnalytics;
GO

-- Create procedure steps table
IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME='eln_experiment_procedure'
)
BEGIN
    CREATE TABLE dbo.eln_experiment_procedure (
        procedure_row_id    INT             NOT NULL PRIMARY KEY,  -- TableRowId
        experiment_id       INT             NOT NULL,
        section_id          INT             NOT NULL,
        step_order          INT                 NULL,
        step_date           NVARCHAR(200)       NULL,
        operation           NVARCHAR(MAX)       NULL,
        quantity            NVARCHAR(200)       NULL,
        time_value          NVARCHAR(200)       NULL,
        temperature         NVARCHAR(200)       NULL,
        observations        NVARCHAR(MAX)       NULL,
        is_header           BIT                 NULL,
        is_active           BIT                 NULL,
        created_date        DATETIME            NULL,
        etl_synced_at       DATETIME            NOT NULL DEFAULT GETDATE()
    );
    PRINT 'Created dbo.eln_experiment_procedure';
END
GO

-- Sync procedure steps
-- Strategy: pivot the 8 columns per row using column position within each row
-- Column positions (by order within row): 1=Date, 2=Operation, 3=Quantity,
-- 4=Time, 5=Time2, 6=Temp, 7=Temp2, 8=Observations
MERGE ELNAnalytics.dbo.eln_experiment_procedure AS tgt
USING (
    SELECT
        tr.TableRowId AS procedure_row_id,
        sr.ContainerId AS experiment_id,
        tr.TableSectionId AS section_id,
        tr.RowOrder AS step_order,
        MAX(CASE WHEN col_pos = 1 THEN tc.ColumnValue END) AS step_date,
        MAX(CASE WHEN col_pos = 2 THEN tc.ColumnValue END) AS operation,
        MAX(CASE WHEN col_pos = 3 THEN tc.ColumnValue END) AS quantity,
        MAX(CASE WHEN col_pos = 4 THEN tc.ColumnValue END) AS time_value,
        MAX(CASE WHEN col_pos = 6 THEN tc.ColumnValue END) AS temperature,
        MAX(CASE WHEN col_pos = 8 THEN tc.ColumnValue END) AS observations,
        tr.IsHeader AS is_header,
        tr.IsActive AS is_active,
        tr.CreatedDate AS created_date
    FROM Atlas.Section.TableRow tr
    JOIN Atlas.Section.Record sr
        ON tr.TableSectionId = sr.SectionId
        AND sr.ContainerTypeId = 10
        AND sr.SectionTypeId = 7   -- Procedure/Process sections only
    JOIN (
        -- Number columns within each row by their TableColumnId order
        SELECT
            tc2.TableColumnId,
            tc2.TableRowId,
            tc2.ColumnValue,
            ROW_NUMBER() OVER (PARTITION BY tc2.TableRowId ORDER BY tc2.TableColumnId) AS col_pos
        FROM Atlas.Section.TableColumn tc2
        WHERE tc2.IsActive = 1
    ) tc ON tr.TableRowId = tc.TableRowId
    WHERE tr.IsActive = 1
    GROUP BY tr.TableRowId, sr.ContainerId, tr.TableSectionId,
             tr.RowOrder, tr.IsHeader, tr.IsActive, tr.CreatedDate
) AS src ON tgt.procedure_row_id = src.procedure_row_id
WHEN NOT MATCHED BY TARGET THEN INSERT (
    procedure_row_id, experiment_id, section_id, step_order,
    step_date, operation, quantity, time_value, temperature,
    observations, is_header, is_active, created_date, etl_synced_at
) VALUES (
    src.procedure_row_id, src.experiment_id, src.section_id, src.step_order,
    src.step_date, src.operation, src.quantity, src.time_value, src.temperature,
    src.observations, src.is_header, src.is_active, src.created_date, GETDATE()
);

DECLARE @proc_count INT = @@ROWCOUNT;
PRINT 'Procedure steps synced: ' + CAST(@proc_count AS VARCHAR);
GO

-- Verify
SELECT 'eln_experiment_procedure' AS tbl, COUNT(*) AS rows FROM dbo.eln_experiment_procedure;
GO

-- Sample: show procedure for experiment 1703
SELECT TOP 10
    step_order, is_header,
    LEFT(ISNULL(operation,''),80) AS operation,
    quantity, temperature,
    LEFT(ISNULL(observations,''),60) AS observations
FROM dbo.eln_experiment_procedure
WHERE experiment_id = 1703 AND is_header = 0
    AND operation IS NOT NULL
ORDER BY step_order;
GO
