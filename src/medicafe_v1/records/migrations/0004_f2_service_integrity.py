from django.db import migrations


FORWARD_SQL = r"""
ALTER TABLE records_identitydecision ADD CONSTRAINT records_decision_service_target_uniq
  UNIQUE (organization_id, patient_id, encounter_id, observation_id, id);
ALTER TABLE records_servicerevision ADD CONSTRAINT records_srev_line_target_uniq
  UNIQUE (organization_id, service_id, encounter_id, patient_id, id);

ALTER TABLE records_service ADD CONSTRAINT records_service_encounter_patient_fk
  FOREIGN KEY (organization_id, patient_id, encounter_id)
  REFERENCES records_encounter (organization_id, patient_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE records_service ADD CONSTRAINT records_service_decision_target_fk
  FOREIGN KEY (organization_id, patient_id, encounter_id, identity_decision_id)
  REFERENCES records_identitydecision (organization_id, patient_id, encounter_id, id)
  DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE records_servicerevision ADD CONSTRAINT records_srev_service_target_fk
  FOREIGN KEY (organization_id, encounter_id, patient_id, service_id)
  REFERENCES records_service (organization_id, encounter_id, patient_id, id)
  DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE records_servicerevision ADD CONSTRAINT records_srev_predecessor_target_fk
  FOREIGN KEY (organization_id, service_id, predecessor_id)
  REFERENCES records_servicerevision (organization_id, service_id, id)
  DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE records_servicerevision ADD CONSTRAINT records_srev_decision_evidence_fk
  FOREIGN KEY (organization_id, patient_id, encounter_id, evidence_observation_id, identity_decision_id)
  REFERENCES records_identitydecision (organization_id, patient_id, encounter_id, observation_id, id)
  DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE records_service ADD CONSTRAINT records_service_head_target_fk
  FOREIGN KEY (organization_id, id, current_revision_id)
  REFERENCES records_servicerevision (organization_id, service_id, id)
  DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE records_recordscommandreceipt ADD CONSTRAINT records_receipt_service_target_fk
  FOREIGN KEY (organization_id, result_service_id)
  REFERENCES records_service (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE records_recordscommandreceipt ADD CONSTRAINT records_receipt_revision_target_fk
  FOREIGN KEY (organization_id, result_service_id, result_revision_id)
  REFERENCES records_servicerevision (organization_id, service_id, id)
  DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE records_servicerevision ADD CONSTRAINT records_srev_reason_nonblank_ck
  CHECK (char_length(btrim(reason)) > 0);
ALTER TABLE records_servicerevision ADD CONSTRAINT records_srev_disposition_ck
  CHECK (disposition IN ('accepted', 'excluded'));
ALTER TABLE records_servicerevision ADD CONSTRAINT records_srev_code_ck
  CHECK (code IN ('SYN-A', 'SYN-B'));
ALTER TABLE records_servicerevision ADD CONSTRAINT records_srev_currency_ck CHECK (currency = 'USD');
ALTER TABLE records_servicerevision ADD CONSTRAINT records_srev_amount_max_ck CHECK (unit_amount <= 9999.99);
ALTER TABLE records_recordscommandreceipt ADD CONSTRAINT records_receipt_kind_ck
  CHECK (command_kind IN ('accept_service', 'revise_service'));
ALTER TABLE records_recordscommandreceipt ADD CONSTRAINT records_receipt_digest_ck
  CHECK (intent_digest ~ '^[0-9a-f]{64}$');

CREATE FUNCTION records_f2_reject_history_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'immutable F2 records row: %', TG_TABLE_NAME USING ERRCODE = '55000';
END;
$$;

CREATE FUNCTION records_f2_revision_sequence_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE predecessor_number integer;
BEGIN
  IF NEW.revision_number = 1 THEN
    IF NEW.predecessor_id IS NOT NULL THEN
      RAISE EXCEPTION 'initial service revision cannot have predecessor' USING ERRCODE = '23514';
    END IF;
  ELSE
    IF NEW.predecessor_id IS NULL THEN
      RAISE EXCEPTION 'service revision predecessor required' USING ERRCODE = '23514';
    END IF;
    SELECT revision_number INTO predecessor_number FROM records_servicerevision
      WHERE organization_id = NEW.organization_id AND service_id = NEW.service_id
        AND id = NEW.predecessor_id;
    IF predecessor_number IS NULL OR NEW.revision_number <> predecessor_number + 1 THEN
      RAISE EXCEPTION 'service revision sequence invalid' USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

CREATE FUNCTION records_f2_service_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE next_predecessor uuid; next_number integer; old_number integer;
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'immutable F2 service' USING ERRCODE = '55000';
  END IF;
  IF ROW(NEW.organization_id, NEW.encounter_id, NEW.patient_id, NEW.identity_decision_id, NEW.created_at)
     IS DISTINCT FROM ROW(OLD.organization_id, OLD.encounter_id, OLD.patient_id, OLD.identity_decision_id, OLD.created_at) THEN
    RAISE EXCEPTION 'immutable F2 service identity' USING ERRCODE = '55000';
  END IF;
  IF NEW.current_revision_id IS NOT DISTINCT FROM OLD.current_revision_id THEN RETURN NEW; END IF;
  IF NEW.current_revision_id IS NULL THEN
    RAISE EXCEPTION 'service head cannot be cleared' USING ERRCODE = '23514';
  END IF;
  SELECT predecessor_id, revision_number INTO next_predecessor, next_number
    FROM records_servicerevision WHERE organization_id = NEW.organization_id
      AND service_id = NEW.id AND id = NEW.current_revision_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'service head target invalid' USING ERRCODE = '23503'; END IF;
  IF OLD.current_revision_id IS NULL THEN
    IF next_predecessor IS NOT NULL OR next_number <> 1 THEN
      RAISE EXCEPTION 'initial service head invalid' USING ERRCODE = '23514';
    END IF;
  ELSE
    SELECT revision_number INTO old_number FROM records_servicerevision
      WHERE organization_id = OLD.organization_id AND service_id = OLD.id AND id = OLD.current_revision_id;
    IF next_predecessor IS DISTINCT FROM OLD.current_revision_id OR next_number <> old_number + 1 THEN
      RAISE EXCEPTION 'service head must advance to direct successor' USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

CREATE FUNCTION records_f2_service_head_required() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actual_head uuid;
BEGIN
  SELECT current_revision_id INTO actual_head FROM records_service WHERE id = NEW.id;
  IF actual_head IS NULL THEN
    RAISE EXCEPTION 'service head required at commit' USING ERRCODE = '23514';
  END IF;
  RETURN NULL;
END;
$$;

CREATE FUNCTION records_f2_revision_is_head() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actual_head uuid;
BEGIN
  SELECT current_revision_id INTO actual_head FROM records_service
    WHERE organization_id = NEW.organization_id AND id = NEW.service_id;
  IF actual_head IS DISTINCT FROM NEW.id AND NOT EXISTS (
      SELECT 1 FROM records_servicerevision WHERE predecessor_id = NEW.id
  ) THEN
    RAISE EXCEPTION 'terminal service revision must be aggregate head' USING ERRCODE = '23514';
  END IF;
  RETURN NULL;
END;
$$;

CREATE TRIGGER records_srev_sequence BEFORE INSERT ON records_servicerevision
  FOR EACH ROW EXECUTE FUNCTION records_f2_revision_sequence_guard();
CREATE TRIGGER records_srev_immutable BEFORE UPDATE OR DELETE ON records_servicerevision
  FOR EACH ROW EXECUTE FUNCTION records_f2_reject_history_change();
CREATE TRIGGER records_receipt_immutable BEFORE UPDATE OR DELETE ON records_recordscommandreceipt
  FOR EACH ROW EXECUTE FUNCTION records_f2_reject_history_change();
CREATE TRIGGER records_service_guard BEFORE UPDATE OR DELETE ON records_service
  FOR EACH ROW EXECUTE FUNCTION records_f2_service_guard();
CREATE CONSTRAINT TRIGGER records_service_head_required AFTER INSERT OR UPDATE ON records_service
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION records_f2_service_head_required();
CREATE CONSTRAINT TRIGGER records_srev_is_head AFTER INSERT ON records_servicerevision
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION records_f2_revision_is_head();
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS records_srev_is_head ON records_servicerevision;
DROP TRIGGER IF EXISTS records_service_head_required ON records_service;
DROP TRIGGER IF EXISTS records_service_guard ON records_service;
DROP TRIGGER IF EXISTS records_receipt_immutable ON records_recordscommandreceipt;
DROP TRIGGER IF EXISTS records_srev_immutable ON records_servicerevision;
DROP TRIGGER IF EXISTS records_srev_sequence ON records_servicerevision;
DROP FUNCTION IF EXISTS records_f2_revision_is_head();
DROP FUNCTION IF EXISTS records_f2_service_head_required();
DROP FUNCTION IF EXISTS records_f2_service_guard();
DROP FUNCTION IF EXISTS records_f2_revision_sequence_guard();
DROP FUNCTION IF EXISTS records_f2_reject_history_change();
ALTER TABLE records_recordscommandreceipt DROP CONSTRAINT IF EXISTS records_receipt_digest_ck;
ALTER TABLE records_recordscommandreceipt DROP CONSTRAINT IF EXISTS records_receipt_kind_ck;
ALTER TABLE records_servicerevision DROP CONSTRAINT IF EXISTS records_srev_amount_max_ck;
ALTER TABLE records_servicerevision DROP CONSTRAINT IF EXISTS records_srev_currency_ck;
ALTER TABLE records_servicerevision DROP CONSTRAINT IF EXISTS records_srev_code_ck;
ALTER TABLE records_servicerevision DROP CONSTRAINT IF EXISTS records_srev_disposition_ck;
ALTER TABLE records_servicerevision DROP CONSTRAINT IF EXISTS records_srev_reason_nonblank_ck;
ALTER TABLE records_recordscommandreceipt DROP CONSTRAINT IF EXISTS records_receipt_revision_target_fk;
ALTER TABLE records_recordscommandreceipt DROP CONSTRAINT IF EXISTS records_receipt_service_target_fk;
ALTER TABLE records_service DROP CONSTRAINT IF EXISTS records_service_head_target_fk;
ALTER TABLE records_servicerevision DROP CONSTRAINT IF EXISTS records_srev_decision_evidence_fk;
ALTER TABLE records_servicerevision DROP CONSTRAINT IF EXISTS records_srev_predecessor_target_fk;
ALTER TABLE records_servicerevision DROP CONSTRAINT IF EXISTS records_srev_service_target_fk;
ALTER TABLE records_service DROP CONSTRAINT IF EXISTS records_service_decision_target_fk;
ALTER TABLE records_service DROP CONSTRAINT IF EXISTS records_service_encounter_patient_fk;
ALTER TABLE records_servicerevision DROP CONSTRAINT IF EXISTS records_srev_line_target_uniq;
ALTER TABLE records_identitydecision DROP CONSTRAINT IF EXISTS records_decision_service_target_uniq;
"""


class Migration(migrations.Migration):
    dependencies = [("records", "0003_service_servicerevision_service_current_revision_and_more")]
    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
