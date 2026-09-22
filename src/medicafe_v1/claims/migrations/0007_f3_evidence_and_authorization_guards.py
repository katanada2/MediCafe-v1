from django.db import migrations


FORWARD_SQL = r"""
ALTER TABLE claims_receiverobservation ADD CONSTRAINT claims_observation_receipt_fingerprint_uniq
  UNIQUE (receiver_id, receiver_version, receipt_id, evidence_fingerprint);
ALTER TABLE claims_receiverobservation ADD CONSTRAINT claims_observation_reported_shape_ck CHECK (
  evidence_fingerprint IS NOT NULL AND evidence_fingerprint ~ '^[0-9a-f]{64}$'
  AND reported_organization_id IS NOT NULL AND reported_intent_id IS NOT NULL
  AND reported_claim_revision_id IS NOT NULL AND reported_delivery_key IS NOT NULL
  AND reported_receiver_id IS NOT NULL AND reported_receiver_version IS NOT NULL
  AND reported_envelope_digest IS NOT NULL AND reported_envelope_digest ~ '^[0-9a-f]{64}$'
  AND reported_byte_length BETWEEN 1 AND 1048576
);

CREATE TABLE claims_receiverreceiptidentity (
  receiver_id varchar(80) NOT NULL,
  receiver_version varchar(20) NOT NULL,
  receipt_id varchar(100) NOT NULL,
  evidence_fingerprint char(64) NOT NULL,
  PRIMARY KEY (receiver_id, receiver_version, receipt_id)
);

CREATE FUNCTION claims_f3_observation_guard_v2() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE intent_row claims_deliveryintent%ROWTYPE; revision_bytes bytea; receipt_conflict boolean;
BEGIN
  SELECT * INTO intent_row FROM claims_deliveryintent WHERE id=NEW.intent_id;
  SELECT envelope_bytes INTO revision_bytes FROM claims_claimrevision
    WHERE id=intent_row.claim_revision_id;
  IF intent_row.id IS NULL THEN
    RAISE EXCEPTION 'receiver observation expected intent missing' USING ERRCODE='23514';
  END IF;
  INSERT INTO claims_receiverreceiptidentity
    (receiver_id,receiver_version,receipt_id,evidence_fingerprint)
    VALUES (NEW.receiver_id,NEW.receiver_version,NEW.receipt_id,NEW.evidence_fingerprint)
    ON CONFLICT (receiver_id,receiver_version,receipt_id) DO NOTHING;
  SELECT anchor.evidence_fingerprint IS DISTINCT FROM NEW.evidence_fingerprint
    INTO receipt_conflict FROM claims_receiverreceiptidentity anchor
    WHERE anchor.receiver_id=NEW.receiver_id AND anchor.receiver_version=NEW.receiver_version
      AND anchor.receipt_id=NEW.receipt_id FOR UPDATE;
  NEW.binding_valid := (
    NOT receipt_conflict
    AND NEW.reported_organization_id = intent_row.organization_id
    AND NEW.reported_intent_id = intent_row.id
    AND NEW.reported_claim_revision_id = intent_row.claim_revision_id
    AND NEW.reported_delivery_key = intent_row.delivery_key
    AND NEW.reported_receiver_id = 'synthetic-receiver'
    AND NEW.reported_receiver_version = intent_row.receiver_version
    AND NEW.reported_envelope_digest = intent_row.envelope_digest
    AND NEW.reported_byte_length = intent_row.byte_length
    AND (
      (NEW.observed_state='accepted' AND NEW.received_bytes = revision_bytes
        AND octet_length(NEW.received_bytes)=intent_row.byte_length
        AND NOT NEW.no_acceptance_guaranteed
        AND EXISTS (SELECT 1 FROM claims_deliveryattempt a
          WHERE a.id=NEW.reported_attempt_id AND a.intent_id=NEW.intent_id AND a.possible_dispatch))
      OR
      (NEW.observed_state='rejected' AND NEW.no_acceptance_guaranteed
        AND EXISTS (SELECT 1 FROM claims_deliveryattempt a
          WHERE a.id=NEW.reported_attempt_id AND a.intent_id=NEW.intent_id AND a.possible_dispatch))
    )
  );
  IF receipt_conflict OR NOT NEW.binding_valid THEN
    NEW.observed_state := 'conflict';
    NEW.binding_valid := FALSE;
    IF NEW.conflict_reason='' THEN
      NEW.conflict_reason := CASE WHEN receipt_conflict THEN 'receipt_identity_conflict' ELSE 'binding_mismatch' END;
    END IF;
  ELSE
    NEW.conflict_reason := '';
  END IF;
  RETURN NEW;
END;
$$;

CREATE FUNCTION claims_f3_intent_shape_guard_v2() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE revision_row claims_claimrevision%ROWTYPE; approval_row claims_claimapproval%ROWTYPE;
BEGIN
  SELECT * INTO revision_row FROM claims_claimrevision WHERE id=NEW.claim_revision_id;
  SELECT * INTO approval_row FROM claims_claimapproval WHERE id=NEW.claim_approval_id;
  IF revision_row.id IS NULL OR approval_row.id IS NULL
     OR revision_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR revision_row.claim_id IS DISTINCT FROM NEW.claim_id
     OR revision_row.envelope_digest IS DISTINCT FROM NEW.envelope_digest
     OR octet_length(revision_row.envelope_bytes) IS DISTINCT FROM NEW.byte_length
     OR revision_row.envelope_format_version IS DISTINCT FROM NEW.format_version
     OR revision_row.route_id IS DISTINCT FROM NEW.route_id
     OR revision_row.route_version IS DISTINCT FROM NEW.receiver_version
     OR approval_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR approval_row.claim_revision_id IS DISTINCT FROM NEW.claim_revision_id
     OR approval_row.envelope_digest IS DISTINCT FROM NEW.envelope_digest THEN
    RAISE EXCEPTION 'delivery intent revision, approval, bytes, or route mismatch' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;

CREATE FUNCTION claims_f3_receipt_guard_v2() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE intent_row claims_deliveryintent%ROWTYPE; work_row claims_deliverywork%ROWTYPE; attempt_row claims_deliveryattempt%ROWTYPE;
BEGIN
  IF NEW.command_kind NOT IN ('request_delivery','cancel_before_dispatch','retry_idempotent_delivery') THEN
    RETURN NULL;
  END IF;
  SELECT * INTO intent_row FROM claims_deliveryintent WHERE id=NEW.result_delivery_intent_id;
  SELECT * INTO work_row FROM claims_deliverywork WHERE id=NEW.result_delivery_work_id;
  IF NEW.accepted_by_id IS NULL OR intent_row.id IS NULL OR work_row.id IS NULL
     OR intent_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR work_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR work_row.intent_id IS DISTINCT FROM intent_row.id THEN
    RAISE EXCEPTION 'F3 receipt actor, intent, or work binding mismatch' USING ERRCODE='23514';
  END IF;
  IF NEW.command_kind='request_delivery' AND (
      NEW.result_claim_id IS DISTINCT FROM intent_row.claim_id
      OR NEW.result_revision_id IS DISTINCT FROM intent_row.claim_revision_id
      OR NEW.result_approval_id IS DISTINCT FROM intent_row.claim_approval_id
      OR (NEW.result_code='delivery_requested' AND (
        intent_row.initial_authorization_receipt_id IS DISTINCT FROM NEW.id
        OR work_row.scheduled_authorization_receipt_id IS DISTINCT FROM NEW.id))) THEN
    RAISE EXCEPTION 'request delivery receipt result mismatch' USING ERRCODE='23514';
  END IF;
  IF NEW.command_kind='retry_idempotent_delivery' THEN
    SELECT * INTO attempt_row FROM claims_deliveryattempt WHERE id=NEW.result_attempt_id;
    IF attempt_row.id IS NULL OR attempt_row.intent_id IS DISTINCT FROM intent_row.id
       OR attempt_row.work_id IS DISTINCT FROM work_row.id
       OR NEW.expected_predecessor_id IS DISTINCT FROM attempt_row.id
       OR (NEW.result_code='delivery_retry_scheduled'
         AND work_row.scheduled_authorization_receipt_id IS DISTINCT FROM NEW.id) THEN
      RAISE EXCEPTION 'retry receipt predecessor or schedule mismatch' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NULL;
END;
$$;

CREATE FUNCTION claims_f3_attempt_guard_v2() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE work_row claims_deliverywork%ROWTYPE; intent_row claims_deliveryintent%ROWTYPE; receipt_row claims_claimscommandreceipt%ROWTYPE;
BEGIN
  SELECT * INTO work_row FROM claims_deliverywork WHERE id=NEW.work_id FOR UPDATE;
  SELECT * INTO intent_row FROM claims_deliveryintent WHERE id=NEW.intent_id;
  SELECT * INTO receipt_row FROM claims_claimscommandreceipt WHERE id=NEW.authorization_receipt_id;
  IF work_row.id IS NULL OR intent_row.id IS NULL OR receipt_row.id IS NULL
     OR work_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR work_row.intent_id IS DISTINCT FROM NEW.intent_id
     OR work_row.state <> 'leased'
     OR work_row.lease_owner IS DISTINCT FROM NEW.lease_owner
     OR work_row.fencing_generation IS DISTINCT FROM NEW.fencing_generation
     OR work_row.scheduled_authorization_receipt_id IS DISTINCT FROM NEW.authorization_receipt_id
     OR work_row.lease_expires_at <= statement_timestamp()
     OR receipt_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR receipt_row.command_kind NOT IN ('request_delivery','retry_idempotent_delivery')
     OR receipt_row.accepted_by_id IS DISTINCT FROM NEW.effective_authorizer_id
     OR receipt_row.result_delivery_intent_id IS DISTINCT FROM NEW.intent_id
     OR receipt_row.result_delivery_work_id IS DISTINCT FROM NEW.work_id
     OR intent_row.envelope_digest IS DISTINCT FROM NEW.payload_digest
     OR intent_row.byte_length IS DISTINCT FROM NEW.byte_length
     OR intent_row.route_id IS DISTINCT FROM NEW.route_id
     OR intent_row.receiver_version IS DISTINCT FROM NEW.receiver_version THEN
    RAISE EXCEPTION 'delivery attempt lease, fence, authorization, or payload mismatch' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;

CREATE FUNCTION claims_f3_outcome_guard_v2() RETURNS trigger LANGUAGE plpgsql AS $$
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
    IF NOT attempt_row.possible_dispatch THEN
      RAISE EXCEPTION 'receiver outcome requires possible dispatch marker' USING ERRCODE='23514';
    END IF;
    SELECT * INTO observation_row FROM claims_receiverobservation WHERE id=NEW.receiver_observation_id;
    IF observation_row.id IS NULL OR NOT observation_row.binding_valid
       OR observation_row.organization_id IS DISTINCT FROM NEW.organization_id
       OR observation_row.intent_id IS DISTINCT FROM attempt_row.intent_id
       OR observation_row.lookup_key IS DISTINCT FROM attempt_row.intent_id
       OR observation_row.envelope_digest IS DISTINCT FROM attempt_row.payload_digest
       OR observation_row.byte_length IS DISTINCT FROM attempt_row.byte_length THEN
      RAISE EXCEPTION 'delivery outcome receiver evidence mismatch' USING ERRCODE='23514';
    END IF;
    IF NEW.kind='receiver_accepted' AND observation_row.observed_state <> 'accepted' THEN
      RAISE EXCEPTION 'accepted outcome requires exact stored-byte evidence' USING ERRCODE='23514';
    END IF;
    IF NEW.kind='receiver_rejected' AND (
      observation_row.observed_state <> 'rejected' OR NOT observation_row.no_acceptance_guaranteed
      OR observation_row.reported_attempt_id IS DISTINCT FROM attempt_row.id) THEN
      RAISE EXCEPTION 'rejected outcome requires attempt-specific no-acceptance evidence' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

CREATE FUNCTION claims_f3_control_guard_v2() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE possible_count integer; rejected_count integer; old_revision integer; new_revision integer;
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
      SELECT r.revision_number INTO old_revision FROM claims_deliveryintent i
        JOIN claims_claimrevision r ON r.id=i.claim_revision_id WHERE i.id=OLD.current_intent_id;
      SELECT r.revision_number INTO new_revision FROM claims_deliveryintent i
        JOIN claims_claimrevision r ON r.id=i.claim_revision_id WHERE i.id=NEW.current_intent_id;
      IF new_revision IS NULL OR old_revision IS NULL OR new_revision <= old_revision THEN
        RAISE EXCEPTION 'claim delivery slot cannot rewind or reuse a revision' USING ERRCODE='23514';
      END IF;
      SELECT count(*) INTO possible_count FROM claims_deliveryattempt
        WHERE intent_id=OLD.current_intent_id AND possible_dispatch;
      SELECT count(DISTINCT a.id) INTO rejected_count
        FROM claims_deliveryattempt a JOIN claims_receiverobservation ro
          ON ro.intent_id=a.intent_id AND ro.reported_attempt_id=a.id
        WHERE a.intent_id=OLD.current_intent_id AND a.possible_dispatch
          AND ro.observed_state='rejected' AND ro.binding_valid AND ro.no_acceptance_guaranteed;
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

DROP TRIGGER claims_attempt_admission ON claims_deliveryattempt;
DROP TRIGGER claims_outcome_admission ON claims_attemptoutcome;
DROP TRIGGER claims_control_guard ON claims_claimdeliverycontrol;
CREATE TRIGGER claims_observation_admission BEFORE INSERT ON claims_receiverobservation
  FOR EACH ROW EXECUTE FUNCTION claims_f3_observation_guard_v2();
CREATE TRIGGER claims_intent_shape BEFORE INSERT ON claims_deliveryintent
  FOR EACH ROW EXECUTE FUNCTION claims_f3_intent_shape_guard_v2();
CREATE CONSTRAINT TRIGGER claims_receipt_f3_binding
  AFTER INSERT ON claims_claimscommandreceipt DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION claims_f3_receipt_guard_v2();
CREATE TRIGGER claims_attempt_admission BEFORE INSERT ON claims_deliveryattempt
  FOR EACH ROW EXECUTE FUNCTION claims_f3_attempt_guard_v2();
CREATE TRIGGER claims_outcome_admission BEFORE INSERT ON claims_attemptoutcome
  FOR EACH ROW EXECUTE FUNCTION claims_f3_outcome_guard_v2();
CREATE TRIGGER claims_control_guard BEFORE INSERT OR UPDATE OR DELETE ON claims_claimdeliverycontrol
  FOR EACH ROW EXECUTE FUNCTION claims_f3_control_guard_v2();
"""


REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS claims_control_guard ON claims_claimdeliverycontrol;
DROP TRIGGER IF EXISTS claims_outcome_admission ON claims_attemptoutcome;
DROP TRIGGER IF EXISTS claims_attempt_admission ON claims_deliveryattempt;
DROP TRIGGER IF EXISTS claims_receipt_f3_binding ON claims_claimscommandreceipt;
DROP TRIGGER IF EXISTS claims_intent_shape ON claims_deliveryintent;
DROP TRIGGER IF EXISTS claims_observation_admission ON claims_receiverobservation;
CREATE TRIGGER claims_attempt_admission BEFORE INSERT ON claims_deliveryattempt
  FOR EACH ROW EXECUTE FUNCTION claims_f3_attempt_guard();
CREATE TRIGGER claims_outcome_admission BEFORE INSERT ON claims_attemptoutcome
  FOR EACH ROW EXECUTE FUNCTION claims_f3_outcome_guard();
CREATE TRIGGER claims_control_guard BEFORE INSERT OR UPDATE OR DELETE ON claims_claimdeliverycontrol
  FOR EACH ROW EXECUTE FUNCTION claims_f3_control_guard();
DROP FUNCTION IF EXISTS claims_f3_control_guard_v2();
DROP FUNCTION IF EXISTS claims_f3_outcome_guard_v2();
DROP FUNCTION IF EXISTS claims_f3_attempt_guard_v2();
DROP FUNCTION IF EXISTS claims_f3_receipt_guard_v2();
DROP FUNCTION IF EXISTS claims_f3_intent_shape_guard_v2();
DROP FUNCTION IF EXISTS claims_f3_observation_guard_v2();
ALTER TABLE claims_receiverobservation DROP CONSTRAINT IF EXISTS claims_observation_reported_shape_ck;
ALTER TABLE claims_receiverobservation DROP CONSTRAINT IF EXISTS claims_observation_receipt_fingerprint_uniq;
DROP TABLE IF EXISTS claims_receiverreceiptidentity;
"""


class Migration(migrations.Migration):
    dependencies = [("claims", "0006_receiverobservation_evidence_fingerprint_and_more")]
    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
