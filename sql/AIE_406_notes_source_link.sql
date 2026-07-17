-- AIE-406: Link project notes to their originating meeting report
-- Run on ELL-VM against ELNAnalytics database, via the App Service SSH
-- tunnel (Stage 2) — Cloud Shell has no VNet path to ELL-VM, so this file
-- is documentation/version control only, not run from Cloud Shell directly.
-- Author: Aqeedat Kaur Sandhu | 2026-07-17

USE ELNAnalytics;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('eln_project_notes') AND name = 'source_report_id'
)
BEGIN
    ALTER TABLE eln_project_notes ADD source_report_id INT NULL;
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = 'FK_notes_source_report')
BEGIN
    ALTER TABLE eln_project_notes
    ADD CONSTRAINT FK_notes_source_report
    FOREIGN KEY (source_report_id) REFERENCES eln_meeting_reports(report_id);
END
GO
