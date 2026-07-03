-- Migration: add report_summary to eln_project_reports
-- Run once on ELL-VM. Safe to re-run.
USE ELNAnalytics;
IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_NAME = 'eln_project_reports' AND COLUMN_NAME = 'report_summary'
)
BEGIN
    ALTER TABLE eln_project_reports ADD report_summary NVARCHAR(MAX) NULL;
    PRINT 'Column added';
END
ELSE PRINT 'Already exists — no change';
