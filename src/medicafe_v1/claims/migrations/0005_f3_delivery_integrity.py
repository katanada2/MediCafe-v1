from django.db import migrations


FORWARD_SQL = r"""
ALTER TABLE claims_claimscommandreceipt DROP CONSTRAINT claims_receipt_kind_ck;
ALTER TABLE claims_claimscommandreceipt DROP CONSTRAINT claims_receipt_result_shape_ck;

ALTER TABLE claims_deliveryintent ADD CONSTRAINT claims_intent_revision_tuple_uniq
  UNIQUE (organization_id, claim_revision_id, id, envelope_digest, byte_length);
ALTER TABLE claims_deliverywork ADD CONSTRAINT claims_work_intent_tuple_uniq
  UNIQUE (organization_id, id, intent_id);
ALTER TABLE claims_deliveryattempt ADD CONSTRAINT claims_attempt_intent_tuple_uniq
  UNIQUE (organization_id, intent_id, id);
ALTER TABLE claims_receiverobservation ADD CONSTRAINT claims_observation_intent_tuple_uniq
  UNIQUE (organization_id, intent_id, id);

ALTER TABLE claims_deliveryintent ADD CONSTRAINT claims_intent_revision_claim_fk
  FOREIGN KEY (organization_id, claim_id, claim_revision_id)
  REFERENCES claims_claimrevision (organization_id, claim_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE claims_deliveryintent ADD CONSTRAINT claims_intent_revision_digest_fk
  FOREIGN KEY (organization_id, claim_revision_id, envelope_digest)
  REFERENCES claims_claimrevision (organization_id, id, envelope_digest) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE claims_deliveryintent ADD CONSTRAINT claims_intent_approval_fk
  FOREIGN KEY (organization_id, claim_revision_id, claim_approval_id)
  REFERENCES claims_claimapproval (organization_id, claim_revision_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE claims_deliveryintent ADD CONSTRAINT claims_intent_receipt_org_fk
  FOREIGN KEY (organization_id, initial_authorization_receipt_id)
  REFERENCES claims_claimscommandreceipt (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE claims_claimdeliverycontrol ADD CONSTRAINT claims_control_intent_fk
  FOREIGN KEY (organization_id, claim_id, current_intent_id)
  REFERENCES claims_deliveryintent (organization_id, claim_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE claims_deliverywork ADD CONSTRAINT claims_work_intent_fk
  FOREIGN KEY (organization_id, intent_id)
  REFERENCES claims_deliveryintent (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE claims_deliverywork ADD CONSTRAINT claims_work_receipt_org_fk
  FOREIGN KEY (organization_id, scheduled_authorization_receipt_id)
  REFERENCES claims_claimscommandreceipt (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE claims_deliveryattempt ADD CONSTRAINT claims_attempt_intent_fk
  FOREIGN KEY (organization_id, intent_id)
  REFERENCES claims_deliveryintent (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE claims_deliveryattempt ADD CONSTRAINT claims_attempt_work_intent_fk
  FOREIGN KEY (organization_id, work_id, intent_id)
  REFERENCES claims_deliverywork (organization_id, id, intent_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE claims_deliveryattempt ADD CONSTRAINT claims_attempt_receipt_org_fk
  FOREIGN KEY (organization_id, authorization_receipt_id)
  REFERENCES claims_claimscommandreceipt (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE claims_receiverobservation ADD CONSTRAINT claims_observation_intent_revision_fk
  FOREIGN KEY (organization_id, claim_revision_id, intent_id, envelope_digest, byte_length)
  REFERENCES claims_deliveryintent
    (organization_id, claim_revision_id, id, envelope_digest, byte_length)
  DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE claims_attemptoutcome ADD CONSTRAINT claims_outcome_attempt_fk
  FOREIGN KEY (organization_id, attempt_id)
  REFERENCES claims_deliveryattempt (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE claims_attemptoutcome ADD CONSTRAINT claims_outcome_observation_fk
  FOREIGN KEY (organization_id, receiver_observation_id)
  REFERENCES claims_receiverobservation (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE claims_claimscommandreceipt ADD CONSTRAINT claims_receipt_intent_org_fk
  FOREIGN KEY (organization_id, result_delivery_intent_id)
  REFERENCES claims_deliveryintent (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE claims_claimscommandreceipt ADD CONSTRAINT claims_receipt_work_org_fk
  FOREIGN KEY (organization_id, result_delivery_work_id)
  REFERENCES claims_deliverywork (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE claims_claimscommandreceipt ADD CONSTRAINT claims_receipt_attempt_org_fk
  FOREIGN KEY (organization_id, result_attempt_id)
  REFERENCES claims_deliveryattempt (organization_id, id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE claims_deliveryintent ADD CONSTRAINT claims_intent_shape_ck CHECK (
  delivery_key = id AND envelope_digest ~ '^[0-9a-f]{64}$'
  AND byte_length BETWEEN 1 AND 1048576
  AND format_version = 'synthetic-json-v1'
  AND route_id = 'synthetic-receiver' AND receiver_version IN ('v1', 'v2')
);
ALTER TABLE claims_deliverywork ADD CONSTRAINT claims_work_shape_ck CHECK (
  fencing_generation >= 0 AND safe_preflight_failures BETWEEN 0 AND 3
  AND state IN ('pending', 'leased', 'blocked', 'finished')
  AND ((state = 'leased' AND lease_owner <> '' AND lease_expires_at IS NOT NULL)
    OR (state <> 'leased'))
);
ALTER TABLE claims_deliveryattempt ADD CONSTRAINT claims_attempt_shape_ck CHECK (
  ordinal >= 1 AND fencing_generation >= 1 AND lease_owner <> ''
  AND payload_digest ~ '^[0-9a-f]{64}$' AND byte_length BETWEEN 1 AND 1048576
  AND route_id = 'synthetic-receiver' AND receiver_version IN ('v1', 'v2')
);
ALTER TABLE claims_receiverobservation ADD CONSTRAINT claims_observation_shape_ck CHECK (
  origin IN ('dispatch_readback', 'reconciliation_readback')
  AND receiver_id = 'synthetic-receiver' AND receiver_version IN ('v1', 'v2')
  AND envelope_digest ~ '^[0-9a-f]{64}$' AND byte_length BETWEEN 1 AND 1048576
  AND observed_state IN ('accepted', 'rejected', 'conflict')
  AND ((observed_state = 'accepted' AND received_bytes IS NOT NULL AND NOT no_acceptance_guaranteed)
    OR (observed_state = 'rejected' AND reported_attempt_id IS NOT NULL AND no_acceptance_guaranteed)
    OR observed_state = 'conflict')
);
ALTER TABLE claims_attemptoutcome ADD CONSTRAINT claims_outcome_shape_ck CHECK (
  kind IN ('pre_dispatch_failed', 'receiver_accepted', 'receiver_rejected', 'unknown')
  AND char_length(btrim(reason)) > 0
  AND ((kind IN ('receiver_accepted', 'receiver_rejected') AND receiver_observation_id IS NOT NULL)
    OR (kind IN ('pre_dispatch_failed', 'unknown') AND receiver_observation_id IS NULL))
);
ALTER TABLE claims_claimscommandreceipt ADD CONSTRAINT claims_receipt_kind_ck CHECK (
  command_kind IN ('prepare_claim_revision', 'approve_claim_revision', 'select_synthetic_policy',
    'request_delivery', 'cancel_before_dispatch', 'retry_idempotent_delivery')
);
ALTER TABLE claims_claimscommandreceipt ADD CONSTRAINT claims_receipt_result_shape_ck CHECK (
  (command_kind = 'prepare_claim_revision'
    AND result_claim_id IS NOT NULL AND result_revision_id IS NOT NULL AND result_approval_id IS NULL
    AND result_policy_version IN ('synthetic-v1', 'synthetic-v2') AND result_policy_generation IS NOT NULL
    AND result_delivery_intent_id IS NULL AND result_delivery_work_id IS NULL AND result_attempt_id IS NULL
    AND result_code = '')
  OR (command_kind = 'approve_claim_revision'
    AND result_claim_id IS NOT NULL AND result_revision_id IS NOT NULL AND result_approval_id IS NOT NULL
    AND result_policy_version IN ('synthetic-v1', 'synthetic-v2') AND result_policy_generation IS NOT NULL
    AND result_delivery_intent_id IS NULL AND result_delivery_work_id IS NULL AND result_attempt_id IS NULL
    AND result_code = '')
  OR (command_kind = 'select_synthetic_policy'
    AND result_claim_id IS NULL AND result_revision_id IS NULL AND result_approval_id IS NULL
    AND result_policy_version IN ('synthetic-v1', 'synthetic-v2') AND result_policy_generation IS NOT NULL
    AND result_delivery_intent_id IS NULL AND result_delivery_work_id IS NULL AND result_attempt_id IS NULL
    AND result_code = '')
  OR (command_kind = 'request_delivery'
    AND accepted_by_id IS NOT NULL
    AND result_claim_id IS NOT NULL AND result_revision_id IS NOT NULL AND result_approval_id IS NOT NULL
    AND result_delivery_intent_id IS NOT NULL AND result_delivery_work_id IS NOT NULL
    AND result_attempt_id IS NULL AND result_code IN ('delivery_requested', 'delivery_coalesced'))
  OR (command_kind = 'cancel_before_dispatch'
    AND accepted_by_id IS NOT NULL
    AND result_claim_id IS NULL AND result_revision_id IS NULL AND result_approval_id IS NULL
    AND result_delivery_intent_id IS NOT NULL AND result_delivery_work_id IS NOT NULL
    AND result_attempt_id IS NULL AND result_code IN ('delivery_cancelled', 'delivery_already_cancelled'))
  OR (command_kind = 'retry_idempotent_delivery'
    AND accepted_by_id IS NOT NULL
    AND result_claim_id IS NULL AND result_revision_id IS NULL AND result_approval_id IS NULL
    AND result_delivery_intent_id IS NOT NULL AND result_delivery_work_id IS NOT NULL
    AND result_attempt_id IS NOT NULL AND result_code IN ('delivery_retry_scheduled', 'delivery_retry_already_scheduled'))
);

CREATE FUNCTION claims_f3_reject_history_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'immutable F3 claims row: %', TG_TABLE_NAME USING ERRCODE = '55000';
END;
$$;

CREATE FUNCTION claims_f3_intent_receipt_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE receipt_org uuid; receipt_kind varchar; receipt_actor uuid; receipt_intent uuid; receipt_work uuid;
BEGIN
  SELECT organization_id, command_kind, accepted_by_id, result_delivery_intent_id,
         result_delivery_work_id
    INTO receipt_org, receipt_kind, receipt_actor, receipt_intent, receipt_work
    FROM claims_claimscommandreceipt WHERE id = NEW.initial_authorization_receipt_id;
  IF receipt_org IS DISTINCT FROM NEW.organization_id OR receipt_kind <> 'request_delivery'
     OR receipt_actor IS DISTINCT FROM NEW.authorized_by_id
     OR receipt_intent IS DISTINCT FROM NEW.id OR receipt_work IS NULL THEN
    RAISE EXCEPTION 'delivery intent authorization receipt mismatch' USING ERRCODE='23514';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM claims_deliverywork w
      WHERE w.id=receipt_work AND w.organization_id=NEW.organization_id AND w.intent_id=NEW.id
        AND w.scheduled_authorization_receipt_id=NEW.initial_authorization_receipt_id
  ) THEN
    RAISE EXCEPTION 'delivery intent work binding mismatch' USING ERRCODE='23514';
  END IF;
  RETURN NULL;
END;
$$;

CREATE FUNCTION claims_f3_attempt_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE work_row claims_deliverywork%ROWTYPE; intent_row claims_deliveryintent%ROWTYPE;
BEGIN
  SELECT * INTO work_row FROM claims_deliverywork WHERE id=NEW.work_id FOR UPDATE;
  SELECT * INTO intent_row FROM claims_deliveryintent WHERE id=NEW.intent_id;
  IF work_row.id IS NULL OR intent_row.id IS NULL
     OR work_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR work_row.intent_id IS DISTINCT FROM NEW.intent_id
     OR work_row.state <> 'leased'
     OR work_row.lease_owner IS DISTINCT FROM NEW.lease_owner
     OR work_row.fencing_generation IS DISTINCT FROM NEW.fencing_generation
     OR work_row.scheduled_authorization_receipt_id IS DISTINCT FROM NEW.authorization_receipt_id
     OR work_row.lease_expires_at <= statement_timestamp()
     OR intent_row.envelope_digest IS DISTINCT FROM NEW.payload_digest
     OR intent_row.byte_length IS DISTINCT FROM NEW.byte_length
     OR intent_row.route_id IS DISTINCT FROM NEW.route_id
     OR intent_row.receiver_version IS DISTINCT FROM NEW.receiver_version THEN
    RAISE EXCEPTION 'delivery attempt lease, fence, authorization, or payload mismatch' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;

CREATE FUNCTION claims_f3_outcome_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE attempt_row claims_deliveryattempt%ROWTYPE; observation_row claims_receiverobservation%ROWTYPE;
BEGIN
  SELECT * INTO attempt_row FROM claims_deliveryattempt WHERE id=NEW.attempt_id;
  IF attempt_row.id IS NULL OR attempt_row.organization_id IS DISTINCT FROM NEW.organization_id THEN
    RAISE EXCEPTION 'delivery outcome attempt mismatch' USING ERRCODE='23514';
  END IF;
  IF NEW.kind='pre_dispatch_failed' AND attempt_row.possible_dispatch THEN
    RAISE EXCEPTION 'possible dispatch cannot be pre-dispatch failure' USING ERRCODE='23514';
  ELSIF NEW.kind='unknown' AND NOT attempt_row.possible_dispatch THEN
    RAISE EXCEPTION 'unknown requires possible dispatch marker' USING ERRCODE='23514';
  ELSIF NEW.kind IN ('receiver_accepted','receiver_rejected') THEN
    SELECT * INTO observation_row FROM claims_receiverobservation WHERE id=NEW.receiver_observation_id;
    IF observation_row.id IS NULL OR NOT observation_row.binding_valid
       OR observation_row.organization_id IS DISTINCT FROM NEW.organization_id
       OR observation_row.intent_id IS DISTINCT FROM attempt_row.intent_id
       OR observation_row.lookup_key IS DISTINCT FROM attempt_row.intent_id
       OR observation_row.envelope_digest IS DISTINCT FROM attempt_row.payload_digest
       OR observation_row.byte_length IS DISTINCT FROM attempt_row.byte_length THEN
      RAISE EXCEPTION 'delivery outcome receiver evidence mismatch' USING ERRCODE='23514';
    END IF;
    IF NEW.kind='receiver_accepted' AND (
      observation_row.observed_state <> 'accepted' OR observation_row.received_bytes IS NULL
      OR octet_length(observation_row.received_bytes) <> attempt_row.byte_length
    ) THEN
      RAISE EXCEPTION 'accepted outcome requires exact stored-byte evidence' USING ERRCODE='23514';
    END IF;
    IF NEW.kind='receiver_rejected' AND (
      observation_row.observed_state <> 'rejected' OR NOT observation_row.no_acceptance_guaranteed
      OR observation_row.reported_attempt_id IS DISTINCT FROM attempt_row.id
    ) THEN
      RAISE EXCEPTION 'rejected outcome requires attempt-specific no-acceptance evidence' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

CREATE FUNCTION claims_f3_control_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE possible_count integer; rejected_count integer;
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'claim delivery control cannot be deleted' USING ERRCODE='55000';
  END IF;
  IF TG_OP='UPDATE' THEN
    IF ROW(NEW.organization_id,NEW.claim_id,NEW.id)
       IS DISTINCT FROM ROW(OLD.organization_id,OLD.claim_id,OLD.id) THEN
      RAISE EXCEPTION 'claim delivery control identity immutable' USING ERRCODE='55000';
    END IF;
    IF NEW.current_intent_id IS DISTINCT FROM OLD.current_intent_id THEN
      SELECT count(*) INTO possible_count FROM claims_deliveryattempt
        WHERE intent_id=OLD.current_intent_id AND possible_dispatch;
      SELECT count(*) INTO rejected_count
        FROM claims_deliveryattempt a JOIN claims_attemptoutcome o ON o.attempt_id=a.id
          JOIN claims_receiverobservation ro ON ro.id=o.receiver_observation_id
        WHERE a.intent_id=OLD.current_intent_id AND a.possible_dispatch
          AND o.kind='receiver_rejected' AND ro.binding_valid AND ro.no_acceptance_guaranteed
          AND ro.reported_attempt_id=a.id;
      IF NOT (
        (possible_count=0 AND EXISTS (
          SELECT 1 FROM claims_claimscommandreceipt r
            WHERE r.command_kind='cancel_before_dispatch'
              AND r.result_delivery_intent_id=OLD.current_intent_id
              AND r.result_code IN ('delivery_cancelled','delivery_already_cancelled')
        )) OR (possible_count>0 AND rejected_count=possible_count
          AND NOT EXISTS (
            SELECT 1 FROM claims_receiverobservation ro
              WHERE ro.intent_id=OLD.current_intent_id
                AND ro.observed_state IN ('accepted','conflict')
          ))
      ) THEN
        RAISE EXCEPTION 'prior delivery intent is not safely releasable' USING ERRCODE='23514';
      END IF;
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

CREATE FUNCTION claims_f3_work_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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

CREATE CONSTRAINT TRIGGER claims_intent_receipt_binding
  AFTER INSERT ON claims_deliveryintent DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION claims_f3_intent_receipt_guard();
CREATE TRIGGER claims_intent_immutable BEFORE UPDATE OR DELETE ON claims_deliveryintent
  FOR EACH ROW EXECUTE FUNCTION claims_f3_reject_history_change();
CREATE TRIGGER claims_attempt_admission BEFORE INSERT ON claims_deliveryattempt
  FOR EACH ROW EXECUTE FUNCTION claims_f3_attempt_guard();
CREATE TRIGGER claims_attempt_immutable BEFORE UPDATE OR DELETE ON claims_deliveryattempt
  FOR EACH ROW EXECUTE FUNCTION claims_f3_reject_history_change();
CREATE TRIGGER claims_observation_immutable BEFORE UPDATE OR DELETE ON claims_receiverobservation
  FOR EACH ROW EXECUTE FUNCTION claims_f3_reject_history_change();
CREATE TRIGGER claims_outcome_admission BEFORE INSERT ON claims_attemptoutcome
  FOR EACH ROW EXECUTE FUNCTION claims_f3_outcome_guard();
CREATE TRIGGER claims_outcome_immutable BEFORE UPDATE OR DELETE ON claims_attemptoutcome
  FOR EACH ROW EXECUTE FUNCTION claims_f3_reject_history_change();
CREATE TRIGGER claims_control_guard BEFORE INSERT OR UPDATE OR DELETE ON claims_claimdeliverycontrol
  FOR EACH ROW EXECUTE FUNCTION claims_f3_control_guard();
CREATE TRIGGER claims_work_guard BEFORE UPDATE OR DELETE ON claims_deliverywork
  FOR EACH ROW EXECUTE FUNCTION claims_f3_work_guard();
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
DROP TRIGGER IF EXISTS claims_work_guard ON claims_deliverywork;
DROP TRIGGER IF EXISTS claims_control_guard ON claims_claimdeliverycontrol;
DROP TRIGGER IF EXISTS claims_outcome_immutable ON claims_attemptoutcome;
DROP TRIGGER IF EXISTS claims_outcome_admission ON claims_attemptoutcome;
DROP TRIGGER IF EXISTS claims_observation_immutable ON claims_receiverobservation;
DROP TRIGGER IF EXISTS claims_attempt_immutable ON claims_deliveryattempt;
DROP TRIGGER IF EXISTS claims_attempt_admission ON claims_deliveryattempt;
DROP TRIGGER IF EXISTS claims_intent_immutable ON claims_deliveryintent;
DROP TRIGGER IF EXISTS claims_intent_receipt_binding ON claims_deliveryintent;
DROP FUNCTION IF EXISTS claims_f3_work_guard();
DROP FUNCTION IF EXISTS claims_f3_control_guard();
DROP FUNCTION IF EXISTS claims_f3_outcome_guard();
DROP FUNCTION IF EXISTS claims_f3_attempt_guard();
DROP FUNCTION IF EXISTS claims_f3_intent_receipt_guard();
DROP FUNCTION IF EXISTS claims_f3_reject_history_change();
ALTER TABLE claims_claimscommandreceipt DROP CONSTRAINT IF EXISTS claims_receipt_result_shape_ck;
ALTER TABLE claims_claimscommandreceipt DROP CONSTRAINT IF EXISTS claims_receipt_kind_ck;
ALTER TABLE claims_attemptoutcome DROP CONSTRAINT IF EXISTS claims_outcome_shape_ck;
ALTER TABLE claims_receiverobservation DROP CONSTRAINT IF EXISTS claims_observation_shape_ck;
ALTER TABLE claims_deliveryattempt DROP CONSTRAINT IF EXISTS claims_attempt_shape_ck;
ALTER TABLE claims_deliverywork DROP CONSTRAINT IF EXISTS claims_work_shape_ck;
ALTER TABLE claims_deliveryintent DROP CONSTRAINT IF EXISTS claims_intent_shape_ck;
ALTER TABLE claims_claimscommandreceipt DROP CONSTRAINT IF EXISTS claims_receipt_attempt_org_fk;
ALTER TABLE claims_claimscommandreceipt DROP CONSTRAINT IF EXISTS claims_receipt_work_org_fk;
ALTER TABLE claims_claimscommandreceipt DROP CONSTRAINT IF EXISTS claims_receipt_intent_org_fk;
ALTER TABLE claims_attemptoutcome DROP CONSTRAINT IF EXISTS claims_outcome_observation_fk;
ALTER TABLE claims_attemptoutcome DROP CONSTRAINT IF EXISTS claims_outcome_attempt_fk;
ALTER TABLE claims_receiverobservation DROP CONSTRAINT IF EXISTS claims_observation_intent_revision_fk;
ALTER TABLE claims_deliveryattempt DROP CONSTRAINT IF EXISTS claims_attempt_receipt_org_fk;
ALTER TABLE claims_deliveryattempt DROP CONSTRAINT IF EXISTS claims_attempt_work_intent_fk;
ALTER TABLE claims_deliveryattempt DROP CONSTRAINT IF EXISTS claims_attempt_intent_fk;
ALTER TABLE claims_deliverywork DROP CONSTRAINT IF EXISTS claims_work_receipt_org_fk;
ALTER TABLE claims_deliverywork DROP CONSTRAINT IF EXISTS claims_work_intent_fk;
ALTER TABLE claims_claimdeliverycontrol DROP CONSTRAINT IF EXISTS claims_control_intent_fk;
ALTER TABLE claims_deliveryintent DROP CONSTRAINT IF EXISTS claims_intent_receipt_org_fk;
ALTER TABLE claims_deliveryintent DROP CONSTRAINT IF EXISTS claims_intent_approval_fk;
ALTER TABLE claims_deliveryintent DROP CONSTRAINT IF EXISTS claims_intent_revision_digest_fk;
ALTER TABLE claims_deliveryintent DROP CONSTRAINT IF EXISTS claims_intent_revision_claim_fk;
ALTER TABLE claims_receiverobservation DROP CONSTRAINT IF EXISTS claims_observation_intent_tuple_uniq;
ALTER TABLE claims_deliveryattempt DROP CONSTRAINT IF EXISTS claims_attempt_intent_tuple_uniq;
ALTER TABLE claims_deliverywork DROP CONSTRAINT IF EXISTS claims_work_intent_tuple_uniq;
ALTER TABLE claims_deliveryintent DROP CONSTRAINT IF EXISTS claims_intent_revision_tuple_uniq;
ALTER TABLE claims_claimscommandreceipt ADD CONSTRAINT claims_receipt_kind_ck
  CHECK (command_kind IN ('prepare_claim_revision', 'approve_claim_revision', 'select_synthetic_policy'));
ALTER TABLE claims_claimscommandreceipt ADD CONSTRAINT claims_receipt_result_shape_ck CHECK (
  (command_kind = 'prepare_claim_revision'
    AND result_claim_id IS NOT NULL AND result_revision_id IS NOT NULL AND result_approval_id IS NULL
    AND result_policy_version IN ('synthetic-v1', 'synthetic-v2') AND result_policy_generation IS NOT NULL)
  OR (command_kind = 'approve_claim_revision'
    AND result_claim_id IS NOT NULL AND result_revision_id IS NOT NULL AND result_approval_id IS NOT NULL
    AND result_policy_version IN ('synthetic-v1', 'synthetic-v2') AND result_policy_generation IS NOT NULL)
  OR (command_kind = 'select_synthetic_policy'
    AND result_claim_id IS NULL AND result_revision_id IS NULL AND result_approval_id IS NULL
    AND result_policy_version IN ('synthetic-v1', 'synthetic-v2') AND result_policy_generation IS NOT NULL)
);
"""


class Migration(migrations.Migration):
    dependencies = [("claims", "0004_claimscommandreceipt_accepted_by_and_more")]
    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
