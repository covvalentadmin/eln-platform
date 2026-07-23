-- AIE-407: Link project notes to their originating chat-uploaded document
-- Mirrors the source_report_id pattern from AIE-406 (report -> note), but
-- for attachment-derived notes (upload -> note). Uploaded files aren't
-- stored in a queryable SQL table (they're blobs in eln-chat-uploads,
-- tracked only by an ephemeral file_id UUID) so this stores the filename
-- directly rather than a foreign key.
-- Run on ELL-VM against ELNAnalytics database, via the App Service SSH
-- tunnel (Stage 2) — Cloud Shell has no VNet path to ELL-VM, so this file
-- is documentation/version control only, not run from Cloud Shell directly.
-- Author: Aqeedat Kaur Sandhu | 2026-07-22

USE ELNAnalytics;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('eln_project_notes') AND name = 'source_upload_filename'
)
BEGIN
    ALTER TABLE eln_project_notes ADD source_upload_filename NVARCHAR(255) NULL;
END
GO
