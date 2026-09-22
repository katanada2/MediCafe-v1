from django.db import migrations


FORWARD_SQL = r"""
CREATE FUNCTION claims_f3_receipt_target_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE intent_row claims_deliveryintent%ROWTYPE;
BEGIN
  IF NEW.command_kind NOT IN ('request_delivery','cancel_before_dispatch','retry_idempotent_delivery') THEN
    RETURN NULL;
  END IF;
  SELECT * INTO intent_row FROM claims_deliveryintent
    WHERE id=NEW.result_delivery_intent_id;
  IF intent_row.id IS NULL
     OR (NEW.command_kind='request_delivery'
       AND NEW.target_key IS DISTINCT FROM intent_row.claim_revision_id::text)
     OR (NEW.command_kind IN ('cancel_before_dispatch','retry_idempotent_delivery')
       AND NEW.target_key IS DISTINCT FROM intent_row.id::text) THEN
    RAISE EXCEPTION 'F3 receipt target does not match its result' USING ERRCODE='23514';
  END IF;
  RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER claims_receipt_f3_target
  AFTER INSERT ON claims_claimscommandreceipt DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION claims_f3_receipt_target_guard();

CREATE FUNCTION claims_f3_observation_route_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE intent_row claims_deliveryintent%ROWTYPE;
BEGIN
  SELECT * INTO intent_row FROM claims_deliveryintent WHERE id=NEW.intent_id;
  IF intent_row.id IS NULL THEN
    RAISE EXCEPTION 'receiver observation expected intent missing' USING ERRCODE='23514';
  END IF;
  IF NEW.lookup_key IS DISTINCT FROM intent_row.delivery_key
     OR NEW.receiver_id IS DISTINCT FROM 'synthetic-receiver'
     OR NEW.receiver_version IS DISTINCT FROM intent_row.receiver_version THEN
    NEW.observed_state := 'conflict';
    NEW.binding_valid := FALSE;
    NEW.conflict_reason := 'binding_mismatch';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER claims_observation_route_guard
  BEFORE INSERT ON claims_receiverobservation
  FOR EACH ROW EXECUTE FUNCTION claims_f3_observation_route_guard();
"""


REVERSE_SQL = r"""
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM claims_deliveryintent)
     OR EXISTS (SELECT 1 FROM claims_claimscommandreceipt
       WHERE command_kind IN ('request_delivery','cancel_before_dispatch','retry_idempotent_delivery')) THEN
    RAISE EXCEPTION 'populated F3 rollback is unsupported; repair forward or restore a consistent pre-F3 backup'
      USING ERRCODE='55000';
  END IF;
END;
$$;
DROP TRIGGER IF EXISTS claims_observation_route_guard ON claims_receiverobservation;
DROP FUNCTION IF EXISTS claims_f3_observation_route_guard();
DROP TRIGGER IF EXISTS claims_receipt_f3_target ON claims_claimscommandreceipt;
DROP FUNCTION IF EXISTS claims_f3_receipt_target_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("claims", "0008_f3_work_transition_guards")]
    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
