from django.db import migrations


FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION claims_f3_work_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE authorization_row claims_claimscommandreceipt%ROWTYPE;
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'delivery work cannot be deleted' USING ERRCODE='55000';
  END IF;
  IF ROW(NEW.organization_id,NEW.intent_id,NEW.id)
     IS DISTINCT FROM ROW(OLD.organization_id,OLD.intent_id,OLD.id) THEN
    RAISE EXCEPTION 'delivery work identity immutable' USING ERRCODE='55000';
  END IF;
  IF NEW.fencing_generation < OLD.fencing_generation
     OR NEW.fencing_generation > OLD.fencing_generation + 1 THEN
    RAISE EXCEPTION 'delivery work fence cannot rewind or skip' USING ERRCODE='23514';
  END IF;
  IF NEW.state='leased' THEN
    IF NEW.lease_owner='' OR NEW.lease_expires_at IS NULL
       OR NEW.lease_expires_at <= statement_timestamp() THEN
      RAISE EXCEPTION 'leased work requires a live owner and expiry' USING ERRCODE='23514';
    END IF;
    IF NEW.fencing_generation <> OLD.fencing_generation + 1 THEN
      RAISE EXCEPTION 'each delivery lease requires a fresh fence' USING ERRCODE='23514';
    END IF;
    IF OLD.state='leased' AND OLD.lease_expires_at > statement_timestamp() THEN
      RAISE EXCEPTION 'live delivery lease cannot be replaced' USING ERRCODE='23514';
    END IF;
  ELSE
    IF NEW.lease_owner<>'' OR NEW.lease_expires_at IS NOT NULL THEN
      RAISE EXCEPTION 'unleased work cannot retain lease authority' USING ERRCODE='23514';
    END IF;
    IF NEW.fencing_generation <> OLD.fencing_generation THEN
      RAISE EXCEPTION 'delivery work fence advances only on lease' USING ERRCODE='23514';
    END IF;
  END IF;
  IF NEW.scheduled_authorization_receipt_id
     IS DISTINCT FROM OLD.scheduled_authorization_receipt_id THEN
    SELECT * INTO authorization_row FROM claims_claimscommandreceipt
      WHERE id=NEW.scheduled_authorization_receipt_id;
    IF OLD.state <> 'finished' OR NEW.state <> 'pending'
       OR NEW.lease_owner<>'' OR NEW.lease_expires_at IS NOT NULL
       OR authorization_row.id IS NULL
       OR authorization_row.organization_id IS DISTINCT FROM NEW.organization_id
       OR authorization_row.command_kind <> 'retry_idempotent_delivery'
       OR authorization_row.result_code <> 'delivery_retry_scheduled'
       OR authorization_row.result_delivery_intent_id IS DISTINCT FROM NEW.intent_id
       OR authorization_row.result_delivery_work_id IS DISTINCT FROM NEW.id THEN
      RAISE EXCEPTION 'delivery authorization can change only for an explicit retry' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
"""


REVERSE_SQL = r"""
CREATE OR REPLACE FUNCTION claims_f3_work_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'delivery work cannot be deleted' USING ERRCODE='55000';
  END IF;
  IF ROW(NEW.organization_id,NEW.intent_id,NEW.id)
     IS DISTINCT FROM ROW(OLD.organization_id,OLD.intent_id,OLD.id) THEN
    RAISE EXCEPTION 'delivery work identity immutable' USING ERRCODE='55000';
  END IF;
  IF NEW.fencing_generation < OLD.fencing_generation
     OR NEW.fencing_generation > OLD.fencing_generation + 1 THEN
    RAISE EXCEPTION 'delivery work fence cannot rewind or skip' USING ERRCODE='23514';
  END IF;
  IF NEW.fencing_generation = OLD.fencing_generation + 1 AND NEW.state <> 'leased' THEN
    RAISE EXCEPTION 'delivery work fence advances only on lease' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
"""


class Migration(migrations.Migration):
    dependencies = [("claims", "0007_f3_evidence_and_authorization_guards")]
    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
