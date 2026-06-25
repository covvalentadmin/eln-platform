-- AIE-401: R&D Intelligence Layer — new tables for ELNAnalytics DB
-- Run on ELL-VM against ELNAnalytics database
-- Author: Aqeedat Kaur Sandhu | 2026-06-25

USE ELNAnalytics;
GO

-- ── Project analysis reports ──────────────────────────────────────────────────
CREATE TABLE eln_project_reports (
    report_id       INT IDENTITY(1,1) PRIMARY KEY,
    project_code    NVARCHAR(20)  NOT NULL,
    generated_date  DATETIME      NOT NULL DEFAULT GETDATE(),
    experiment_count INT,
    blob_url        NVARCHAR(500),
    triggered_by    NVARCHAR(50),   -- 'manual' or 'weekly_automation'
    generated_by    NVARCHAR(100),  -- user login
    status          NVARCHAR(20)  DEFAULT 'pending'  -- pending/complete/failed
);
GO

-- ── Meeting copilot reports ───────────────────────────────────────────────────
CREATE TABLE eln_meeting_reports (
    report_id       INT IDENTITY(1,1) PRIMARY KEY,
    generated_date  DATETIME      NOT NULL DEFAULT GETDATE(),
    project_code    NVARCHAR(20),
    topic           NVARCHAR(200),
    blob_url        NVARCHAR(500),
    transcript      TEXT,
    author          NVARCHAR(100),
    status          NVARCHAR(20)  DEFAULT 'pending'
);
GO

-- ── Project notes (captured context) ─────────────────────────────────────────
CREATE TABLE eln_project_notes (
    note_id         INT IDENTITY(1,1) PRIMARY KEY,
    project_code    NVARCHAR(20)  NOT NULL,
    note_text       NVARCHAR(MAX) NOT NULL,
    captured_from   NVARCHAR(50),   -- 'chat' or 'manual'
    author          NVARCHAR(100),
    created_date    DATETIME      NOT NULL DEFAULT GETDATE(),
    is_deleted      BIT           DEFAULT 0
);
GO

-- ── Indexes ───────────────────────────────────────────────────────────────────
CREATE INDEX idx_reports_project  ON eln_project_reports(project_code);
CREATE INDEX idx_notes_project    ON eln_project_notes(project_code, is_deleted);
GO
