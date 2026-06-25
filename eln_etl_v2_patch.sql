/*
  eln_etl_v2_patch.sql — Fixes SQL Server 2019 Express CONCAT-in-PRINT issue
  Replaces usp_ELN_ETL with corrected version.
  Run after eln_etl_v2.sql has already created the new tables.
*/

USE ELNAnalytics;
GO

IF OBJECT_ID('dbo.usp_ELN_ETL', 'P') IS NOT NULL
    DROP PROCEDURE dbo.usp_ELN_ETL;
GO

CREATE PROCEDURE dbo.usp_ELN_ETL
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE
        @run_start              DATETIME    = GETDATE(),
        @projects_count         INT         = 0,
        @teams_count            INT         = 0,
        @requests_count         INT         = 0,
        @materials_count        INT         = 0,
        @experiments_count      INT         = 0,
        @exp_materials_count    INT         = 0,
        @exp_products_count     INT         = 0,
        @exp_tlc_count          INT         = 0,
        @status                 VARCHAR(20) = 'failed',
        @error_msg              VARCHAR(MAX)= NULL,
        @log_id                 INT;

    INSERT INTO dbo.eln_etl_log (run_started_at, status)
    VALUES (@run_start, 'running');
    SET @log_id = SCOPE_IDENTITY();

    BEGIN TRY

        -- 1. Projects
        MERGE ELNAnalytics.dbo.eln_projects AS tgt
        USING (
            SELECT ProjectId, Code AS project_code, Title AS title,
                GenericName AS generic_name, CASNumber AS cas_number,
                IUPACName AS iupac_name,
                CAST(StartDate AS DATE) AS start_date,
                CAST(EndDate AS DATE) AS end_date,
                ProjectStatus AS project_status, IsRMProject AS is_rm_project,
                PrimaryProjectType AS primary_project_type,
                OrganizationId AS organization_id, ClientId AS client_id,
                CreatedDate AS created_date, UpdatedDate AS updated_date
            FROM Condor.Project.RecordEx WHERE IsActive = 1
        ) AS src ON tgt.project_id = src.ProjectId
        WHEN MATCHED AND tgt.updated_date <> src.updated_date
        THEN UPDATE SET
            project_code=src.project_code, title=src.title,
            generic_name=src.generic_name, cas_number=src.cas_number,
            iupac_name=src.iupac_name, start_date=src.start_date,
            end_date=src.end_date, project_status=src.project_status,
            is_rm_project=src.is_rm_project,
            primary_project_type=src.primary_project_type,
            organization_id=src.organization_id, client_id=src.client_id,
            created_date=src.created_date, updated_date=src.updated_date,
            etl_synced_at=GETDATE()
        WHEN NOT MATCHED BY TARGET THEN INSERT (
            project_id, project_code, title, generic_name, cas_number,
            iupac_name, start_date, end_date, project_status, is_rm_project,
            primary_project_type, organization_id, client_id,
            created_date, updated_date, etl_synced_at
        ) VALUES (
            src.ProjectId, src.project_code, src.title, src.generic_name,
            src.cas_number, src.iupac_name, src.start_date, src.end_date,
            src.project_status, src.is_rm_project, src.primary_project_type,
            src.organization_id, src.client_id,
            src.created_date, src.updated_date, GETDATE()
        );
        SET @projects_count = @@ROWCOUNT;

        -- 2. Project Teams
        MERGE ELNAnalytics.dbo.eln_project_teams AS tgt
        USING (
            SELECT ProjectTeamId, ProjectId, TeamCode, DepartmentId,
                CAST(StartDate AS DATE) AS start_date,
                CAST(EndDate AS DATE) AS end_date,
                ProjectStatus, Conclusion, Remarks, NextActionPlan,
                TotalBudget, LabelClaim, LabelClaimUnit,
                IsRMProjectTeam, IsActive, CreatedDate, UpdatedDate
            FROM Condor.Project.ProjectTeam WHERE IsActive = 1
        ) AS src ON tgt.project_team_id = src.ProjectTeamId
        WHEN MATCHED AND tgt.updated_date <> src.UpdatedDate
        THEN UPDATE SET
            project_id=src.ProjectId, team_code=src.TeamCode,
            department_id=src.DepartmentId, start_date=src.start_date,
            end_date=src.end_date, project_status=src.ProjectStatus,
            conclusion=src.Conclusion, remarks=src.Remarks,
            next_action_plan=src.NextActionPlan, total_budget=src.TotalBudget,
            label_claim=src.LabelClaim, label_claim_unit=src.LabelClaimUnit,
            is_rm_project_team=src.IsRMProjectTeam, is_active=src.IsActive,
            created_date=src.CreatedDate, updated_date=src.UpdatedDate,
            etl_synced_at=GETDATE()
        WHEN NOT MATCHED BY TARGET THEN INSERT (
            project_team_id, project_id, team_code, department_id,
            start_date, end_date, project_status, conclusion, remarks,
            next_action_plan, total_budget, label_claim, label_claim_unit,
            is_rm_project_team, is_active, created_date, updated_date, etl_synced_at
        ) VALUES (
            src.ProjectTeamId, src.ProjectId, src.TeamCode, src.DepartmentId,
            src.start_date, src.end_date, src.ProjectStatus, src.Conclusion,
            src.Remarks, src.NextActionPlan, src.TotalBudget, src.LabelClaim,
            src.LabelClaimUnit, src.IsRMProjectTeam, src.IsActive,
            src.CreatedDate, src.UpdatedDate, GETDATE()
        );
        SET @teams_count = @@ROWCOUNT;

        -- 3. Requests
        MERGE ELNAnalytics.dbo.eln_requests AS tgt
        USING (
            SELECT RequestId, RequestNumber, RequestStatus,
                ProjectTeamId, Notes, IsActive, CreatedDate, UpdatedDate
            FROM Condor.Inventory.Request WHERE IsActive = 1
        ) AS src ON tgt.request_id = src.RequestId
        WHEN MATCHED AND tgt.updated_date <> src.UpdatedDate
        THEN UPDATE SET
            request_number=src.RequestNumber, request_status=src.RequestStatus,
            project_team_id=src.ProjectTeamId, notes=src.Notes,
            is_active=src.IsActive, created_date=src.CreatedDate,
            updated_date=src.UpdatedDate, etl_synced_at=GETDATE()
        WHEN NOT MATCHED BY TARGET THEN INSERT (
            request_id, request_number, request_status, project_team_id,
            notes, is_active, created_date, updated_date, etl_synced_at
        ) VALUES (
            src.RequestId, src.RequestNumber, src.RequestStatus,
            src.ProjectTeamId, src.Notes, src.IsActive,
            src.CreatedDate, src.UpdatedDate, GETDATE()
        );
        SET @requests_count = @@ROWCOUNT;

        -- 4. Requested Materials
        MERGE ELNAnalytics.dbo.eln_requested_materials AS tgt
        USING (
            SELECT rm.MaterialRequestId, rm.RequestId, rm.MaterialId,
                COALESCE(m.MaterialName, rm.RequestedMaterialName) AS material_name,
                COALESCE(m.CASNumber, rm.RequestedCASNumber) AS cas_number,
                rm.Quantity, rm.Unit, rm.Purity, rm.Supplier,
                rm.BatchNumber, rm.RequiredByDate, rm.IsActive,
                rm.CreatedDate, rm.UpdatedDate
            FROM Condor.Inventory.RequestedMaterials rm
            LEFT JOIN Condor.Inventory.Material m ON rm.MaterialId = m.MaterialId
            WHERE rm.IsActive = 1
        ) AS src ON tgt.material_request_id = src.MaterialRequestId
        WHEN MATCHED AND tgt.updated_date <> src.UpdatedDate
        THEN UPDATE SET
            request_id=src.RequestId, material_id=src.MaterialId,
            material_name=src.material_name, cas_number=src.cas_number,
            quantity=src.Quantity, unit=src.Unit, purity=src.Purity,
            supplier=src.Supplier, batch_number=src.BatchNumber,
            required_by_date=src.RequiredByDate, is_active=src.IsActive,
            created_date=src.CreatedDate, updated_date=src.UpdatedDate,
            etl_synced_at=GETDATE()
        WHEN NOT MATCHED BY TARGET THEN INSERT (
            material_request_id, request_id, material_id, material_name,
            cas_number, quantity, unit, purity, supplier, batch_number,
            required_by_date, is_active, created_date, updated_date, etl_synced_at
        ) VALUES (
            src.MaterialRequestId, src.RequestId, src.MaterialId,
            src.material_name, src.cas_number, src.Quantity, src.Unit,
            src.Purity, src.Supplier, src.BatchNumber, src.RequiredByDate,
            src.IsActive, src.CreatedDate, src.UpdatedDate, GETDATE()
        );
        SET @materials_count = @@ROWCOUNT;

        -- 5. Experiments (Atlas)
        MERGE ELNAnalytics.dbo.eln_experiments AS tgt
        USING (
            SELECT ExperimentId, ProjectTeamId, ExperimentStatus,
                Prefix, ExperimentNumber, Title, Objective, Conclusion,
                NextActionPlan, FinalOutcome,
                CAST(StartDate AS DATE) AS start_date,
                CAST(EndDate AS DATE) AS end_date,
                IsMarkedComplete, IsActive, CreatedDate, UpdatedDate
            FROM Atlas.Experiment.Record WHERE IsActive = 1
        ) AS src ON tgt.experiment_id = src.ExperimentId
        WHEN MATCHED AND tgt.updated_date <> src.UpdatedDate
        THEN UPDATE SET
            project_team_id=src.ProjectTeamId,
            experiment_status=src.ExperimentStatus,
            prefix=src.Prefix, experiment_number=src.ExperimentNumber,
            title=src.Title, objective=src.Objective,
            conclusion=src.Conclusion, next_action_plan=src.NextActionPlan,
            final_outcome=src.FinalOutcome, start_date=src.start_date,
            end_date=src.end_date, is_marked_complete=src.IsMarkedComplete,
            is_active=src.IsActive, created_date=src.CreatedDate,
            updated_date=src.UpdatedDate, etl_synced_at=GETDATE()
        WHEN NOT MATCHED BY TARGET THEN INSERT (
            experiment_id, project_team_id, experiment_status, prefix,
            experiment_number, title, objective, conclusion, next_action_plan,
            final_outcome, start_date, end_date, is_marked_complete,
            is_active, created_date, updated_date, etl_synced_at
        ) VALUES (
            src.ExperimentId, src.ProjectTeamId, src.ExperimentStatus,
            src.Prefix, src.ExperimentNumber, src.Title, src.Objective,
            src.Conclusion, src.NextActionPlan, src.FinalOutcome,
            src.start_date, src.end_date, src.IsMarkedComplete,
            src.IsActive, src.CreatedDate, src.UpdatedDate, GETDATE()
        );
        SET @experiments_count = @@ROWCOUNT;

        -- 6. Experiment Sections
        MERGE ELNAnalytics.dbo.eln_experiment_sections AS tgt
        USING (
            SELECT SectionId, ContainerId AS ExperimentId,
                SectionTypeId, SectionTitle, SectionOrder,
                IsActive, CreatedDate
            FROM Atlas.Section.Record WHERE ContainerTypeId = 10
        ) AS src ON tgt.section_id = src.SectionId
        WHEN NOT MATCHED BY TARGET THEN INSERT (
            section_id, experiment_id, section_type_id, section_title,
            section_order, is_active, created_date, etl_synced_at
        ) VALUES (
            src.SectionId, src.ExperimentId, src.SectionTypeId,
            src.SectionTitle, src.SectionOrder,
            src.IsActive, src.CreatedDate, GETDATE()
        );

        -- 7. Experiment Raw Materials
        MERGE ELNAnalytics.dbo.eln_experiment_materials AS tgt
        USING (
            SELECT rm.RawMaterialId, rm.ChemicalReactionSectionId,
                sr.ContainerId AS ExperimentId,
                rm.RawMaterialName, rm.CASNumber, rm.MolecularFormula,
                rm.Quantity, rm.Unit, rm.Purity, rm.Batch,
                rm.Moles, rm.Ratio, rm.IsLimitingAgent,
                rm.Remarks, rm.IsActive, rm.CreatedDate
            FROM Atlas.Section.RawMaterials rm
            JOIN Atlas.Section.Record sr
                ON rm.ChemicalReactionSectionId = sr.SectionId
                AND sr.ContainerTypeId = 10
            WHERE rm.IsActive = 1
        ) AS src ON tgt.raw_material_id = src.RawMaterialId
        WHEN NOT MATCHED BY TARGET THEN INSERT (
            raw_material_id, reaction_section_id, experiment_id,
            raw_material_name, cas_number, molecular_formula,
            quantity, unit, purity, batch, moles, ratio,
            is_limiting_agent, remarks, is_active, created_date, etl_synced_at
        ) VALUES (
            src.RawMaterialId, src.ChemicalReactionSectionId, src.ExperimentId,
            src.RawMaterialName, src.CASNumber, src.MolecularFormula,
            src.Quantity, src.Unit, src.Purity, src.Batch,
            src.Moles, src.Ratio, src.IsLimitingAgent,
            src.Remarks, src.IsActive, src.CreatedDate, GETDATE()
        );
        SET @exp_materials_count = @@ROWCOUNT;

        -- 8. Reaction Products + Yields
        MERGE ELNAnalytics.dbo.eln_experiment_products AS tgt
        USING (
            SELECT rp.ReactionProductId, rp.QASectionId,
                sr.ContainerId AS ExperimentId,
                rp.ProductName, rp.MolecularFormula, rp.MolecularWeight,
                rp.IUPACName, rpy.DryWt, rpy.CrudeYield, rpy.PurifiedYield,
                rpy.Purity, rpy.TheoreticalCrudeYield,
                rpy.AtomEconomy, rpy.EFactorActual,
                rp.IsActive, rp.CreatedDate
            FROM Atlas.Section.ReactionProduct rp
            LEFT JOIN Atlas.Section.ReactionProductYield rpy
                ON rp.ReactionProductId = rpy.ReactionProductId
            JOIN Atlas.Section.Record sr
                ON rp.QASectionId = sr.SectionId
                AND sr.ContainerTypeId = 10
            WHERE rp.IsActive = 1
        ) AS src ON tgt.reaction_product_id = src.ReactionProductId
        WHEN NOT MATCHED BY TARGET THEN INSERT (
            reaction_product_id, reaction_section_id, experiment_id,
            product_name, molecular_formula, molecular_weight, iupac_name,
            dry_wt, crude_yield, purified_yield, purity,
            theoretical_crude_yield, atom_economy, e_factor_actual,
            is_active, created_date, etl_synced_at
        ) VALUES (
            src.ReactionProductId, src.QASectionId, src.ExperimentId,
            src.ProductName, src.MolecularFormula, src.MolecularWeight,
            src.IUPACName, src.DryWt, src.CrudeYield, src.PurifiedYield,
            src.Purity, src.TheoreticalCrudeYield, src.AtomEconomy,
            src.EFactorActual, src.IsActive, src.CreatedDate, GETDATE()
        );
        SET @exp_products_count = @@ROWCOUNT;

        -- 9. TLC
        MERGE ELNAnalytics.dbo.eln_experiment_tlc AS tgt
        USING (
            SELECT t.TLCPlateId, t.TLCSectionId,
                sr.ContainerId AS ExperimentId,
                t.PlateTitle, t.PlateNotes,
                t.SpotANotes, t.RF1, t.SpotBNotes, t.RF2,
                t.SpotCNotes, t.RF3, t.SpotDNotes, t.RF4,
                t.IsActive, t.CreatedDate
            FROM Atlas.Section.TLC t
            JOIN Atlas.Section.Record sr
                ON t.TLCSectionId = sr.SectionId
                AND sr.ContainerTypeId = 10
            WHERE t.IsActive = 1
        ) AS src ON tgt.tlc_plate_id = src.TLCPlateId
        WHEN NOT MATCHED BY TARGET THEN INSERT (
            tlc_plate_id, tlc_section_id, experiment_id,
            plate_title, plate_notes,
            spot_a_notes, rf1, spot_b_notes, rf2,
            spot_c_notes, rf3, spot_d_notes, rf4,
            is_active, created_date, etl_synced_at
        ) VALUES (
            src.TLCPlateId, src.TLCSectionId, src.ExperimentId,
            src.PlateTitle, src.PlateNotes,
            src.SpotANotes, src.RF1, src.SpotBNotes, src.RF2,
            src.SpotCNotes, src.RF3, src.SpotDNotes, src.RF4,
            src.IsActive, src.CreatedDate, GETDATE()
        );
        SET @exp_tlc_count = @@ROWCOUNT;

        SET @status = 'success';

    END TRY
    BEGIN CATCH
        SET @status    = 'failed';
        SET @error_msg = 'Error ' + CAST(ERROR_NUMBER() AS VARCHAR) +
                         ' line ' + CAST(ERROR_LINE() AS VARCHAR) +
                         ': ' + ERROR_MESSAGE();
        PRINT @error_msg;
    END CATCH

    UPDATE dbo.eln_etl_log SET
        run_finished_at    = GETDATE(),
        status             = @status,
        projects_upserted  = @projects_count,
        teams_upserted     = @teams_count,
        requests_upserted  = @requests_count,
        materials_upserted = @materials_count,
        error_message      = @error_msg
    WHERE log_id = @log_id;

    PRINT 'Status      : ' + UPPER(@status);
    PRINT 'Projects    : ' + CAST(@projects_count AS VARCHAR);
    PRINT 'Teams       : ' + CAST(@teams_count AS VARCHAR);
    PRINT 'Requests    : ' + CAST(@requests_count AS VARCHAR);
    PRINT 'Materials   : ' + CAST(@materials_count AS VARCHAR);
    PRINT 'Experiments : ' + CAST(@experiments_count AS VARCHAR);
    PRINT 'Exp Matls   : ' + CAST(@exp_materials_count AS VARCHAR);
    PRINT 'Exp Products: ' + CAST(@exp_products_count AS VARCHAR);
    PRINT 'TLC records : ' + CAST(@exp_tlc_count AS VARCHAR);

END;
GO

PRINT 'Running ETL v2 patch...';
EXEC dbo.usp_ELN_ETL;
GO

SELECT 'eln_projects'               AS tbl, COUNT(*) AS rows FROM dbo.eln_projects
UNION ALL SELECT 'eln_experiments',          COUNT(*) FROM dbo.eln_experiments
UNION ALL SELECT 'eln_experiment_sections',  COUNT(*) FROM dbo.eln_experiment_sections
UNION ALL SELECT 'eln_experiment_materials', COUNT(*) FROM dbo.eln_experiment_materials
UNION ALL SELECT 'eln_experiment_products',  COUNT(*) FROM dbo.eln_experiment_products
UNION ALL SELECT 'eln_experiment_tlc',       COUNT(*) FROM dbo.eln_experiment_tlc
UNION ALL SELECT 'eln_etl_log',              COUNT(*) FROM dbo.eln_etl_log;
GO
