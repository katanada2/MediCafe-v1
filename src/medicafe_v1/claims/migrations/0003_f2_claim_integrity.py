from django.db import migrations


FORWARD_SQL = r"""
ALTER TABLE claims_claimrevision ADD CONSTRAINT claims_rev_approval_target_uniq
  UNIQUE (organization_id, id, envelope_digest);
ALTER TABLE claims_claimrevision ADD CONSTRAINT claims_rev_line_target_uniq
  UNIQUE (organization_id, claim_id, encounter_id, patient_id, id);
ALTER TABLE claims_claimrevision ADD CONSTRAINT claims_rev_receipt_policy_target_uniq
  UNIQUE (organization_id, id, policy_version, policy_generation);
ALTER TABLE claims_claimapproval ADD CONSTRAINT claims_approval_receipt_target_uniq
  UNIQUE (organization_id, claim_revision_id, id);

ALTER TABLE claims_claim ADD CONSTRAINT claims_case_encounter_patient_fk
  FOREIGN KEY (organization_id, patient_id, encounter_id)
  REFERENCES records_encounter (organization_id, patient_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE claims_claimrevision ADD CONSTRAINT claims_rev_case_target_fk
  FOREIGN KEY (organization_id, encounter_id, patient_id, claim_id)
  REFERENCES claims_claim (organization_id, encounter_id, patient_id, id)
  DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE claims_claimrevision ADD CONSTRAINT claims_rev_predecessor_target_fk
  FOREIGN KEY (organization_id, claim_id, predecessor_id)
  REFERENCES claims_claimrevision (organization_id, claim_id, id)
  DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE claims_claim ADD CONSTRAINT claims_case_head_target_fk
  FOREIGN KEY (organization_id, id, current_revision_id)
  REFERENCES claims_claimrevision (organization_id, claim_id, id)
  DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE claims_claimline ADD CONSTRAINT claims_line_revision_target_fk
  FOREIGN KEY (organization_id, claim_id, encounter_id, patient_id, claim_revision_id)
  REFERENCES claims_claimrevision (organization_id, claim_id, encounter_id, patient_id, id)
  DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE claims_claimline ADD CONSTRAINT claims_line_service_target_fk
  FOREIGN KEY (organization_id, encounter_id, patient_id, service_id)
  REFERENCES records_service (organization_id, encounter_id, patient_id, id)
  DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE claims_claimline ADD CONSTRAINT claims_line_srev_target_fk
  FOREIGN KEY (organization_id, service_id, encounter_id, patient_id, service_revision_id)
  REFERENCES records_servicerevision (organization_id, service_id, encounter_id, patient_id, id)
  DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE claims_claimapproval ADD CONSTRAINT claims_approval_revision_digest_fk
  FOREIGN KEY (organization_id, claim_revision_id, envelope_digest)
  REFERENCES claims_claimrevision (organization_id, id, envelope_digest)
  DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE claims_claimscommandreceipt ADD CONSTRAINT claims_receipt_claim_target_fk
  FOREIGN KEY (organization_id, result_claim_id)
  REFERENCES claims_claim (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE claims_claimscommandreceipt ADD CONSTRAINT claims_receipt_revision_target_fk
  FOREIGN KEY (organization_id, result_revision_id)
  REFERENCES claims_claimrevision (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE claims_claimscommandreceipt ADD CONSTRAINT claims_receipt_approval_target_fk
  FOREIGN KEY (organization_id, result_approval_id)
  REFERENCES claims_claimapproval (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE claims_claimscommandreceipt ADD CONSTRAINT claims_receipt_claim_revision_pair_fk
  FOREIGN KEY (organization_id, result_claim_id, result_revision_id)
  REFERENCES claims_claimrevision (organization_id, claim_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE claims_claimscommandreceipt ADD CONSTRAINT claims_receipt_revision_approval_pair_fk
  FOREIGN KEY (organization_id, result_revision_id, result_approval_id)
  REFERENCES claims_claimapproval (organization_id, claim_revision_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE claims_claimscommandreceipt ADD CONSTRAINT claims_receipt_revision_policy_pair_fk
  FOREIGN KEY (organization_id, result_revision_id, result_policy_version, result_policy_generation)
  REFERENCES claims_claimrevision (organization_id, id, policy_version, policy_generation)
  DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE claims_syntheticpolicyselection ADD CONSTRAINT claims_policy_version_ck
  CHECK (version IN ('synthetic-v1', 'synthetic-v2'));
ALTER TABLE claims_claimrevision ADD CONSTRAINT claims_rev_reason_nonblank_ck CHECK (char_length(btrim(reason)) > 0);
ALTER TABLE claims_claimrevision ADD CONSTRAINT claims_rev_route_ck
  CHECK ((route_id = 'synthetic-receiver' AND route_version IN ('v1', 'v2')));
ALTER TABLE claims_claimrevision ADD CONSTRAINT claims_rev_format_ck CHECK (envelope_format_version = 'synthetic-json-v1');
ALTER TABLE claims_claimrevision ADD CONSTRAINT claims_rev_envelope_size_ck
  CHECK (octet_length(envelope_bytes) BETWEEN 1 AND 1048576);
ALTER TABLE claims_claimrevision ADD CONSTRAINT claims_rev_digest_shape_ck CHECK (envelope_digest ~ '^[0-9a-f]{64}$');
ALTER TABLE claims_claimrevision ADD CONSTRAINT claims_rev_currency_ck CHECK (currency = 'USD');
ALTER TABLE claims_claimline ADD CONSTRAINT claims_line_code_ck CHECK (code IN ('SYN-A', 'SYN-B'));
ALTER TABLE claims_claimline ADD CONSTRAINT claims_line_currency_ck CHECK (currency = 'USD');
ALTER TABLE claims_claimline ADD CONSTRAINT claims_line_units_ck CHECK (units BETWEEN 1 AND 100);
ALTER TABLE claims_claimline ADD CONSTRAINT claims_line_unit_amount_ck CHECK (unit_amount BETWEEN 0 AND 9999.99);
ALTER TABLE claims_claimscommandreceipt ADD CONSTRAINT claims_receipt_kind_ck
  CHECK (command_kind IN ('prepare_claim_revision', 'approve_claim_revision', 'select_synthetic_policy'));
ALTER TABLE claims_claimscommandreceipt ADD CONSTRAINT claims_receipt_digest_ck CHECK (intent_digest ~ '^[0-9a-f]{64}$');
ALTER TABLE claims_claimscommandreceipt ADD CONSTRAINT claims_receipt_result_shape_ck CHECK (
  (command_kind = 'prepare_claim_revision'
    AND result_claim_id IS NOT NULL AND result_revision_id IS NOT NULL AND result_approval_id IS NULL
    AND result_policy_version IN ('synthetic-v1', 'synthetic-v2') AND result_policy_generation IS NOT NULL)
  OR
  (command_kind = 'approve_claim_revision'
    AND result_claim_id IS NOT NULL AND result_revision_id IS NOT NULL AND result_approval_id IS NOT NULL
    AND result_policy_version IN ('synthetic-v1', 'synthetic-v2') AND result_policy_generation IS NOT NULL)
  OR
  (command_kind = 'select_synthetic_policy'
    AND result_claim_id IS NULL AND result_revision_id IS NULL AND result_approval_id IS NULL
    AND result_policy_version IN ('synthetic-v1', 'synthetic-v2') AND result_policy_generation IS NOT NULL)
);

CREATE FUNCTION claims_f2_reject_history_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'immutable F2 claims row: %', TG_TABLE_NAME USING ERRCODE = '55000';
END;
$$;

CREATE FUNCTION claims_f2_revision_sequence_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE predecessor_number integer;
BEGIN
  IF NEW.revision_number = 1 THEN
    IF NEW.predecessor_id IS NOT NULL THEN RAISE EXCEPTION 'initial claim revision predecessor invalid' USING ERRCODE='23514'; END IF;
  ELSE
    IF NEW.predecessor_id IS NULL THEN RAISE EXCEPTION 'claim predecessor required' USING ERRCODE='23514'; END IF;
    SELECT revision_number INTO predecessor_number FROM claims_claimrevision
      WHERE organization_id=NEW.organization_id AND claim_id=NEW.claim_id AND id=NEW.predecessor_id;
    IF predecessor_number IS NULL OR NEW.revision_number <> predecessor_number + 1 THEN
      RAISE EXCEPTION 'claim revision sequence invalid' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

CREATE FUNCTION claims_f2_case_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE next_predecessor uuid; next_number integer; old_number integer;
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'immutable F2 claim case' USING ERRCODE='55000'; END IF;
  IF ROW(NEW.organization_id,NEW.encounter_id,NEW.patient_id,NEW.created_at)
     IS DISTINCT FROM ROW(OLD.organization_id,OLD.encounter_id,OLD.patient_id,OLD.created_at) THEN
    RAISE EXCEPTION 'immutable F2 claim identity' USING ERRCODE='55000';
  END IF;
  IF NEW.current_revision_id IS NOT DISTINCT FROM OLD.current_revision_id THEN RETURN NEW; END IF;
  IF NEW.current_revision_id IS NULL THEN RAISE EXCEPTION 'claim head cannot be cleared' USING ERRCODE='23514'; END IF;
  SELECT predecessor_id,revision_number INTO next_predecessor,next_number FROM claims_claimrevision
    WHERE organization_id=NEW.organization_id AND claim_id=NEW.id AND id=NEW.current_revision_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'claim head target invalid' USING ERRCODE='23503'; END IF;
  IF OLD.current_revision_id IS NULL THEN
    IF next_predecessor IS NOT NULL OR next_number <> 1 THEN RAISE EXCEPTION 'initial claim head invalid' USING ERRCODE='23514'; END IF;
  ELSE
    SELECT revision_number INTO old_number FROM claims_claimrevision
      WHERE organization_id=OLD.organization_id AND claim_id=OLD.id AND id=OLD.current_revision_id;
    IF next_predecessor IS DISTINCT FROM OLD.current_revision_id OR next_number <> old_number + 1 THEN
      RAISE EXCEPTION 'claim head must advance to direct successor' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

CREATE FUNCTION claims_f2_case_head_required() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actual_head uuid;
BEGIN
  SELECT current_revision_id INTO actual_head FROM claims_claim WHERE id=NEW.id;
  IF actual_head IS NULL THEN RAISE EXCEPTION 'claim head required at commit' USING ERRCODE='23514'; END IF;
  RETURN NULL;
END;
$$;

CREATE FUNCTION claims_f2_revision_is_head() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actual_head uuid;
BEGIN
  SELECT current_revision_id INTO actual_head FROM claims_claim WHERE organization_id=NEW.organization_id AND id=NEW.claim_id;
  IF actual_head IS DISTINCT FROM NEW.id AND NOT EXISTS (SELECT 1 FROM claims_claimrevision WHERE predecessor_id=NEW.id) THEN
    RAISE EXCEPTION 'terminal claim revision must be aggregate head' USING ERRCODE='23514';
  END IF;
  RETURN NULL;
END;
$$;

CREATE FUNCTION claims_f2_policy_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'policy selection cannot be deleted' USING ERRCODE='55000'; END IF;
  IF TG_OP='INSERT' THEN
    IF NEW.activation_generation <> 1 THEN RAISE EXCEPTION 'initial policy generation must be one' USING ERRCODE='23514'; END IF;
    RETURN NEW;
  END IF;
  IF NEW.organization_id IS DISTINCT FROM OLD.organization_id OR NEW.id IS DISTINCT FROM OLD.id THEN
    RAISE EXCEPTION 'policy identity immutable' USING ERRCODE='55000';
  END IF;
  IF NEW.version = OLD.version THEN
    IF NEW.activation_generation <> OLD.activation_generation
       OR NEW.selected_by_id IS DISTINCT FROM OLD.selected_by_id
       OR NEW.selected_at IS DISTINCT FROM OLD.selected_at THEN
      RAISE EXCEPTION 'same policy selection is immutable' USING ERRCODE='23514';
    END IF;
  ELSIF NEW.activation_generation <> OLD.activation_generation + 1 THEN
    RAISE EXCEPTION 'policy change must increment generation' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER claims_rev_sequence BEFORE INSERT ON claims_claimrevision FOR EACH ROW EXECUTE FUNCTION claims_f2_revision_sequence_guard();
CREATE TRIGGER claims_rev_immutable BEFORE UPDATE OR DELETE ON claims_claimrevision FOR EACH ROW EXECUTE FUNCTION claims_f2_reject_history_change();
CREATE TRIGGER claims_line_immutable BEFORE UPDATE OR DELETE ON claims_claimline FOR EACH ROW EXECUTE FUNCTION claims_f2_reject_history_change();
CREATE TRIGGER claims_approval_immutable BEFORE UPDATE OR DELETE ON claims_claimapproval FOR EACH ROW EXECUTE FUNCTION claims_f2_reject_history_change();
CREATE TRIGGER claims_receipt_immutable BEFORE UPDATE OR DELETE ON claims_claimscommandreceipt FOR EACH ROW EXECUTE FUNCTION claims_f2_reject_history_change();
CREATE TRIGGER claims_case_guard BEFORE UPDATE OR DELETE ON claims_claim FOR EACH ROW EXECUTE FUNCTION claims_f2_case_guard();
CREATE TRIGGER claims_policy_guard BEFORE INSERT OR UPDATE OR DELETE ON claims_syntheticpolicyselection FOR EACH ROW EXECUTE FUNCTION claims_f2_policy_guard();
CREATE CONSTRAINT TRIGGER claims_case_head_required AFTER INSERT OR UPDATE ON claims_claim
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION claims_f2_case_head_required();
CREATE CONSTRAINT TRIGGER claims_rev_is_head AFTER INSERT ON claims_claimrevision
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION claims_f2_revision_is_head();
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS claims_rev_is_head ON claims_claimrevision;
DROP TRIGGER IF EXISTS claims_case_head_required ON claims_claim;
DROP TRIGGER IF EXISTS claims_policy_guard ON claims_syntheticpolicyselection;
DROP TRIGGER IF EXISTS claims_case_guard ON claims_claim;
DROP TRIGGER IF EXISTS claims_receipt_immutable ON claims_claimscommandreceipt;
DROP TRIGGER IF EXISTS claims_approval_immutable ON claims_claimapproval;
DROP TRIGGER IF EXISTS claims_line_immutable ON claims_claimline;
DROP TRIGGER IF EXISTS claims_rev_immutable ON claims_claimrevision;
DROP TRIGGER IF EXISTS claims_rev_sequence ON claims_claimrevision;
DROP FUNCTION IF EXISTS claims_f2_policy_guard();
DROP FUNCTION IF EXISTS claims_f2_revision_is_head();
DROP FUNCTION IF EXISTS claims_f2_case_head_required();
DROP FUNCTION IF EXISTS claims_f2_case_guard();
DROP FUNCTION IF EXISTS claims_f2_revision_sequence_guard();
DROP FUNCTION IF EXISTS claims_f2_reject_history_change();
ALTER TABLE claims_claimscommandreceipt DROP CONSTRAINT IF EXISTS claims_receipt_digest_ck;
ALTER TABLE claims_claimscommandreceipt DROP CONSTRAINT IF EXISTS claims_receipt_result_shape_ck;
ALTER TABLE claims_claimscommandreceipt DROP CONSTRAINT IF EXISTS claims_receipt_kind_ck;
ALTER TABLE claims_claimline DROP CONSTRAINT IF EXISTS claims_line_unit_amount_ck;
ALTER TABLE claims_claimline DROP CONSTRAINT IF EXISTS claims_line_units_ck;
ALTER TABLE claims_claimline DROP CONSTRAINT IF EXISTS claims_line_currency_ck;
ALTER TABLE claims_claimline DROP CONSTRAINT IF EXISTS claims_line_code_ck;
ALTER TABLE claims_claimrevision DROP CONSTRAINT IF EXISTS claims_rev_currency_ck;
ALTER TABLE claims_claimrevision DROP CONSTRAINT IF EXISTS claims_rev_digest_shape_ck;
ALTER TABLE claims_claimrevision DROP CONSTRAINT IF EXISTS claims_rev_envelope_size_ck;
ALTER TABLE claims_claimrevision DROP CONSTRAINT IF EXISTS claims_rev_format_ck;
ALTER TABLE claims_claimrevision DROP CONSTRAINT IF EXISTS claims_rev_route_ck;
ALTER TABLE claims_claimrevision DROP CONSTRAINT IF EXISTS claims_rev_reason_nonblank_ck;
ALTER TABLE claims_syntheticpolicyselection DROP CONSTRAINT IF EXISTS claims_policy_version_ck;
ALTER TABLE claims_claimscommandreceipt DROP CONSTRAINT IF EXISTS claims_receipt_approval_target_fk;
ALTER TABLE claims_claimscommandreceipt DROP CONSTRAINT IF EXISTS claims_receipt_revision_policy_pair_fk;
ALTER TABLE claims_claimscommandreceipt DROP CONSTRAINT IF EXISTS claims_receipt_revision_approval_pair_fk;
ALTER TABLE claims_claimscommandreceipt DROP CONSTRAINT IF EXISTS claims_receipt_claim_revision_pair_fk;
ALTER TABLE claims_claimscommandreceipt DROP CONSTRAINT IF EXISTS claims_receipt_revision_target_fk;
ALTER TABLE claims_claimscommandreceipt DROP CONSTRAINT IF EXISTS claims_receipt_claim_target_fk;
ALTER TABLE claims_claimapproval DROP CONSTRAINT IF EXISTS claims_approval_receipt_target_uniq;
ALTER TABLE claims_claimrevision DROP CONSTRAINT IF EXISTS claims_rev_receipt_policy_target_uniq;
ALTER TABLE claims_claimapproval DROP CONSTRAINT IF EXISTS claims_approval_revision_digest_fk;
ALTER TABLE claims_claimline DROP CONSTRAINT IF EXISTS claims_line_srev_target_fk;
ALTER TABLE claims_claimline DROP CONSTRAINT IF EXISTS claims_line_service_target_fk;
ALTER TABLE claims_claimline DROP CONSTRAINT IF EXISTS claims_line_revision_target_fk;
ALTER TABLE claims_claim DROP CONSTRAINT IF EXISTS claims_case_head_target_fk;
ALTER TABLE claims_claimrevision DROP CONSTRAINT IF EXISTS claims_rev_predecessor_target_fk;
ALTER TABLE claims_claimrevision DROP CONSTRAINT IF EXISTS claims_rev_case_target_fk;
ALTER TABLE claims_claim DROP CONSTRAINT IF EXISTS claims_case_encounter_patient_fk;
ALTER TABLE claims_claimrevision DROP CONSTRAINT IF EXISTS claims_rev_line_target_uniq;
ALTER TABLE claims_claimrevision DROP CONSTRAINT IF EXISTS claims_rev_approval_target_uniq;
"""


class Migration(migrations.Migration):
    dependencies = [("claims", "0002_initial"), ("records", "0004_f2_service_integrity")]
    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
