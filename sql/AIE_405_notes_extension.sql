-- AIE-405: Extend eln_project_notes with experiment linkage, note type, and verification flag
-- Run on ELL-VM against ELNAnalytics database
-- Author: Aqeedat Kaur Sandhu | 2026-07-16

USE ELNAnalytics;
GO

-- ── Link a note to a specific experiment (optional) ──────────────────────────
ALTER TABLE eln_project_notes ADD exp_number_full NVARCHAR(50) NULL;
GO

-- ── Classify notes as a decision or a data point ──────────────────────────────
ALTER TABLE eln_project_notes ADD note_type NVARCHAR(20) NOT NULL
    CONSTRAINT DF_eln_project_notes_note_type DEFAULT 'decision'
    CONSTRAINT CK_eln_project_notes_note_type CHECK (note_type IN ('decision', 'data_point'));
GO

-- ── Reserved for future verification workflow ─────────────────────────────────
ALTER TABLE eln_project_notes ADD verified BIT NOT NULL DEFAULT 0;
GO

-- ── Indexes ───────────────────────────────────────────────────────────────────
CREATE INDEX idx_notes_exp ON eln_project_notes(exp_number_full) WHERE exp_number_full IS NOT NULL;
GO
