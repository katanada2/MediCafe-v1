from django.db import migrations


FORWARD_SQL = r"""
CREATE FUNCTION archival_f4_reject_history_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'F4 archive history is immutable' USING ERRCODE='55000';
END;
$$;

DO $$ DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'archival_archiveprojection','archival_archivebatch',
    'archival_archivecommandreceipt','archival_archiveauthorization',
    'archival_archivebatchitem','archival_archiveattempt',
    'archival_archivereadbackobservation','archival_archiveattemptoutcome'
  ] LOOP
    EXECUTE format(
      'CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %I '
      'FOR EACH ROW EXECUTE FUNCTION archival_f4_reject_history_change()',
      table_name || '_immutable', table_name
    );
  END LOOP;
END;
$$;

CREATE TABLE archival_archivereceiptidentity (
  receiver_id varchar(80) NOT NULL,
  receiver_version varchar(20) NOT NULL,
  target_receipt_id varchar(100) NOT NULL,
  evidence_fingerprint char(64) NOT NULL,
  PRIMARY KEY (receiver_id,receiver_version,target_receipt_id)
);
CREATE TRIGGER archival_receiptidentity_immutable
  BEFORE UPDATE OR DELETE ON archival_archivereceiptidentity
  FOR EACH ROW EXECUTE FUNCTION archival_f4_reject_history_change();

CREATE FUNCTION archival_f4_projection_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE encounter_row records_encounter%ROWTYPE; predecessor_row archival_archiveprojection%ROWTYPE;
BEGIN
  SELECT * INTO encounter_row FROM records_encounter WHERE id=NEW.encounter_id;
  IF encounter_row.id IS NULL OR encounter_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR NEW.source_fingerprint !~ '^[0-9a-f]{64}$'
     OR NEW.projection_digest !~ '^[0-9a-f]{64}$'
     OR encode(sha256(NEW.projection_bytes),'hex') IS DISTINCT FROM NEW.projection_digest
     OR octet_length(NEW.projection_bytes) IS DISTINCT FROM NEW.byte_length
     OR NEW.byte_length < 1 OR NEW.byte_length > 2097152 THEN
    RAISE EXCEPTION 'archive projection encounter or bytes mismatch' USING ERRCODE='23514';
  END IF;
  IF NEW.version=1 THEN
    IF NEW.predecessor_id IS NOT NULL THEN
      RAISE EXCEPTION 'initial archive projection cannot name predecessor' USING ERRCODE='23514';
    END IF;
  ELSE
    SELECT * INTO predecessor_row FROM archival_archiveprojection WHERE id=NEW.predecessor_id;
    IF predecessor_row.id IS NULL
       OR predecessor_row.organization_id IS DISTINCT FROM NEW.organization_id
       OR predecessor_row.encounter_id IS DISTINCT FROM NEW.encounter_id
       OR predecessor_row.version+1 IS DISTINCT FROM NEW.version THEN
      RAISE EXCEPTION 'archive projection predecessor mismatch' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER archival_projection_admission
  BEFORE INSERT ON archival_archiveprojection
  FOR EACH ROW EXECUTE FUNCTION archival_f4_projection_guard();

CREATE FUNCTION archival_f4_head_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE projection_row archival_archiveprojection%ROWTYPE; old_version integer;
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'archive head cannot be deleted' USING ERRCODE='55000';
  END IF;
  SELECT * INTO projection_row FROM archival_archiveprojection WHERE id=NEW.projection_id;
  IF projection_row.id IS NULL
     OR projection_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR projection_row.encounter_id IS DISTINCT FROM NEW.encounter_id THEN
    RAISE EXCEPTION 'archive head projection mismatch' USING ERRCODE='23514';
  END IF;
  IF TG_OP='UPDATE' THEN
    IF ROW(NEW.id,NEW.organization_id,NEW.encounter_id)
       IS DISTINCT FROM ROW(OLD.id,OLD.organization_id,OLD.encounter_id) THEN
      RAISE EXCEPTION 'archive head identity immutable' USING ERRCODE='55000';
    END IF;
    SELECT version INTO old_version FROM archival_archiveprojection WHERE id=OLD.projection_id;
    IF projection_row.version <= old_version
       OR projection_row.predecessor_id IS DISTINCT FROM OLD.projection_id THEN
      RAISE EXCEPTION 'archive head cannot rewind or skip predecessor' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER archival_head_guard
  BEFORE INSERT OR UPDATE OR DELETE ON archival_archivehead
  FOR EACH ROW EXECUTE FUNCTION archival_f4_head_guard();

CREATE FUNCTION archival_f4_receipt_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE projection_row archival_archiveprojection%ROWTYPE; batch_row archival_archivebatch%ROWTYPE;
        auth_row archival_archiveauthorization%ROWTYPE; item_count integer;
BEGIN
  IF NEW.intent_digest !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'archive receipt digest invalid' USING ERRCODE='23514';
  END IF;
  IF NEW.command_kind='capture_archive_projection' THEN
    SELECT * INTO projection_row FROM archival_archiveprojection WHERE id=NEW.result_projection_id;
    IF projection_row.id IS NULL OR projection_row.organization_id IS DISTINCT FROM NEW.organization_id
       OR NEW.result_batch_id IS NOT NULL OR NEW.result_authorization_id IS NOT NULL
       OR NEW.target_key IS DISTINCT FROM projection_row.encounter_id::text THEN
      RAISE EXCEPTION 'archive capture receipt result mismatch' USING ERRCODE='23514';
    END IF;
  ELSIF NEW.command_kind='queue_archive_batch' THEN
    SELECT * INTO batch_row FROM archival_archivebatch WHERE id=NEW.result_batch_id;
    SELECT count(*) INTO item_count FROM archival_archivebatchitem
     WHERE batch_id=NEW.result_batch_id;
    IF batch_row.id IS NULL OR batch_row.organization_id IS DISTINCT FROM NEW.organization_id
       OR NEW.result_projection_id IS NOT NULL OR NEW.result_authorization_id IS NOT NULL
       OR NEW.target_key IS DISTINCT FROM batch_row.id::text
       OR item_count < 1 OR item_count > 100
       OR EXISTS (
         SELECT 1 FROM generate_series(1,item_count) ordinal
          WHERE NOT EXISTS (
            SELECT 1 FROM archival_archivebatchitem item
             WHERE item.batch_id=NEW.result_batch_id AND item.ordinal=ordinal
          )
       ) THEN
      RAISE EXCEPTION 'archive queue receipt result mismatch' USING ERRCODE='23514';
    END IF;
  ELSIF NEW.command_kind='retry_archive_item' THEN
    SELECT * INTO projection_row FROM archival_archiveprojection WHERE id=NEW.result_projection_id;
    SELECT * INTO auth_row FROM archival_archiveauthorization WHERE id=NEW.result_authorization_id;
    IF projection_row.id IS NULL OR auth_row.id IS NULL
       OR projection_row.organization_id IS DISTINCT FROM NEW.organization_id
       OR auth_row.organization_id IS DISTINCT FROM NEW.organization_id
       OR auth_row.projection_id IS DISTINCT FROM projection_row.id
       OR NEW.result_batch_id IS NOT NULL
       OR NEW.target_key IS DISTINCT FROM projection_row.id::text THEN
      RAISE EXCEPTION 'archive retry receipt result mismatch' USING ERRCODE='23514';
    END IF;
  ELSE
    RAISE EXCEPTION 'archive receipt command kind unsupported' USING ERRCODE='23514';
  END IF;
  RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER archival_receipt_admission
  AFTER INSERT ON archival_archivecommandreceipt DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION archival_f4_receipt_guard();

CREATE FUNCTION archival_f4_authorization_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE projection_row archival_archiveprojection%ROWTYPE;
        receipt_row archival_archivecommandreceipt%ROWTYPE;
        predecessor_row archival_archiveattempt%ROWTYPE;
BEGIN
  SELECT * INTO projection_row FROM archival_archiveprojection WHERE id=NEW.projection_id;
  SELECT * INTO receipt_row FROM archival_archivecommandreceipt WHERE id=NEW.command_receipt_id;
  IF projection_row.id IS NULL OR receipt_row.id IS NULL
     OR projection_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR receipt_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR NEW.receiver_id <> 'synthetic-archive' OR NEW.receiver_version <> 'v1' THEN
    RAISE EXCEPTION 'archive authorization projection, receipt, or receiver mismatch'
      USING ERRCODE='23514';
  END IF;
  IF NEW.kind='initial_queue' THEN
    IF receipt_row.command_kind <> 'queue_archive_batch'
       OR NEW.allowed_attempts <> 3 OR NEW.expected_predecessor_attempt_id IS NOT NULL
       OR NOT EXISTS (
         SELECT 1 FROM archival_archivebatchitem item
          WHERE item.batch_id=receipt_row.result_batch_id
            AND item.projection_id=NEW.projection_id
            AND item.authorization_id=NEW.id
       ) THEN
      RAISE EXCEPTION 'initial archive authorization mismatch' USING ERRCODE='23514';
    END IF;
  ELSIF NEW.kind='manual_retry' THEN
    SELECT * INTO predecessor_row FROM archival_archiveattempt
     WHERE id=NEW.expected_predecessor_attempt_id;
    IF receipt_row.command_kind <> 'retry_archive_item'
       OR receipt_row.result_authorization_id IS DISTINCT FROM NEW.id
       OR receipt_row.result_projection_id IS DISTINCT FROM NEW.projection_id
       OR NEW.allowed_attempts <> 1 OR predecessor_row.id IS NULL
       OR predecessor_row.organization_id IS DISTINCT FROM NEW.organization_id
       OR predecessor_row.projection_id IS DISTINCT FROM NEW.projection_id
       OR predecessor_row.receiver_id IS DISTINCT FROM NEW.receiver_id
       OR predecessor_row.receiver_version IS DISTINCT FROM NEW.receiver_version THEN
      RAISE EXCEPTION 'manual archive authorization predecessor mismatch' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
CREATE CONSTRAINT TRIGGER archival_authorization_admission
  AFTER INSERT ON archival_archiveauthorization DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION archival_f4_authorization_guard();

CREATE FUNCTION archival_f4_work_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE projection_row archival_archiveprojection%ROWTYPE;
        auth_row archival_archiveauthorization%ROWTYPE;
        latest_attempt archival_archiveattempt%ROWTYPE;
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'archive work cannot be deleted' USING ERRCODE='55000';
  END IF;
  SELECT * INTO projection_row FROM archival_archiveprojection WHERE id=NEW.projection_id;
  SELECT * INTO auth_row FROM archival_archiveauthorization WHERE id=NEW.scheduled_authorization_id;
  IF projection_row.id IS NULL OR auth_row.id IS NULL
     OR projection_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR auth_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR auth_row.projection_id IS DISTINCT FROM NEW.projection_id THEN
    RAISE EXCEPTION 'archive work projection or authorization mismatch' USING ERRCODE='23514';
  END IF;
  IF (NEW.state='leased' AND (
        NEW.lease_owner='' OR NEW.lease_expires_at IS NULL
        OR NEW.lease_expires_at <= statement_timestamp()
      )) OR (NEW.state<>'leased' AND (
        NEW.lease_owner<>'' OR NEW.lease_expires_at IS NOT NULL
      )) THEN
    RAISE EXCEPTION 'archive work lease shape invalid' USING ERRCODE='23514';
  END IF;
  IF TG_OP='UPDATE' THEN
    IF ROW(NEW.id,NEW.organization_id,NEW.projection_id)
       IS DISTINCT FROM ROW(OLD.id,OLD.organization_id,OLD.projection_id)
       OR NEW.fencing_generation < OLD.fencing_generation THEN
      RAISE EXCEPTION 'archive work identity or fence cannot rewind' USING ERRCODE='55000';
    END IF;
    IF NEW.state='leased' THEN
      IF OLD.state <> 'pending'
         OR NEW.fencing_generation <> OLD.fencing_generation+1 THEN
        RAISE EXCEPTION 'archive lease requires pending state and a fresh fence'
          USING ERRCODE='23514';
      END IF;
    ELSIF NEW.fencing_generation <> OLD.fencing_generation THEN
      RAISE EXCEPTION 'archive fence changes only on pending to leased transition'
        USING ERRCODE='23514';
    END IF;
    IF OLD.state='leased' AND OLD.lease_expires_at <= statement_timestamp()
       AND NEW.state='pending' THEN
      SELECT * INTO latest_attempt FROM archival_archiveattempt
       WHERE work_id=OLD.id AND fencing_generation=OLD.fencing_generation
       ORDER BY started_at DESC,id DESC LIMIT 1;
      IF latest_attempt.id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM archival_archiveattemptoutcome outcome
         WHERE outcome.attempt_id=latest_attempt.id
      ) THEN
        RAISE EXCEPTION 'expired possible write requires a terminal outcome before recovery'
          USING ERRCODE='23514';
      END IF;
    END IF;
    IF NEW.scheduled_authorization_id IS DISTINCT FROM OLD.scheduled_authorization_id
       AND (auth_row.kind <> 'manual_retry'
            OR OLD.state NOT IN ('finished','blocked')
            OR NEW.state <> 'pending'
            OR NEW.fencing_generation <> OLD.fencing_generation) THEN
      RAISE EXCEPTION 'archive work authorization replacement requires manual retry'
        USING ERRCODE='23514';
    END IF;
  ELSIF NEW.state <> 'pending' OR NEW.fencing_generation <> 0 THEN
    RAISE EXCEPTION 'new archive work must start pending at fence zero' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER archival_work_guard
  BEFORE INSERT OR UPDATE OR DELETE ON archival_archivework
  FOR EACH ROW EXECUTE FUNCTION archival_f4_work_guard();

CREATE FUNCTION archival_f4_item_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE batch_row archival_archivebatch%ROWTYPE; work_row archival_archivework%ROWTYPE;
        auth_row archival_archiveauthorization%ROWTYPE; projection_row archival_archiveprojection%ROWTYPE;
BEGIN
  SELECT * INTO batch_row FROM archival_archivebatch WHERE id=NEW.batch_id;
  SELECT * INTO work_row FROM archival_archivework WHERE id=NEW.work_id;
  SELECT * INTO auth_row FROM archival_archiveauthorization WHERE id=NEW.authorization_id;
  SELECT * INTO projection_row FROM archival_archiveprojection WHERE id=NEW.projection_id;
  IF batch_row.id IS NULL OR work_row.id IS NULL OR auth_row.id IS NULL OR projection_row.id IS NULL
     OR batch_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR work_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR auth_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR projection_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR work_row.projection_id IS DISTINCT FROM NEW.projection_id
     OR auth_row.projection_id IS DISTINCT FROM NEW.projection_id
     OR work_row.scheduled_authorization_id IS DISTINCT FROM NEW.authorization_id THEN
    RAISE EXCEPTION 'archive batch item relationship mismatch' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER archival_item_admission
  BEFORE INSERT ON archival_archivebatchitem
  FOR EACH ROW EXECUTE FUNCTION archival_f4_item_guard();

CREATE FUNCTION archival_f4_attempt_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE work_row archival_archivework%ROWTYPE; auth_row archival_archiveauthorization%ROWTYPE;
        projection_row archival_archiveprojection%ROWTYPE; used integer;
BEGIN
  SELECT * INTO work_row FROM archival_archivework WHERE id=NEW.work_id FOR UPDATE;
  SELECT * INTO auth_row FROM archival_archiveauthorization WHERE id=NEW.authorization_id;
  SELECT * INTO projection_row FROM archival_archiveprojection WHERE id=NEW.projection_id;
  SELECT count(*) INTO used FROM archival_archiveattempt
   WHERE authorization_id=NEW.authorization_id AND possible_write;
  IF work_row.id IS NULL OR auth_row.id IS NULL OR projection_row.id IS NULL
     OR work_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR auth_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR projection_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR work_row.projection_id IS DISTINCT FROM NEW.projection_id
     OR work_row.scheduled_authorization_id IS DISTINCT FROM NEW.authorization_id
     OR auth_row.projection_id IS DISTINCT FROM NEW.projection_id
     OR work_row.state <> 'leased' OR work_row.lease_owner IS DISTINCT FROM NEW.lease_owner
     OR work_row.fencing_generation IS DISTINCT FROM NEW.fencing_generation
     OR work_row.lease_expires_at IS NULL
     OR work_row.lease_expires_at <= statement_timestamp()
     OR NEW.receiver_id IS DISTINCT FROM auth_row.receiver_id
     OR NEW.receiver_version IS DISTINCT FROM auth_row.receiver_version
     OR NEW.projection_digest IS DISTINCT FROM projection_row.projection_digest
     OR NEW.byte_length IS DISTINCT FROM projection_row.byte_length
     OR (NEW.possible_write AND used >= auth_row.allowed_attempts) THEN
    RAISE EXCEPTION 'archive attempt lease, grant, projection, or budget mismatch'
      USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER archival_attempt_admission
  BEFORE INSERT ON archival_archiveattempt
  FOR EACH ROW EXECUTE FUNCTION archival_f4_attempt_guard();

CREATE FUNCTION archival_f4_observation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE projection_row archival_archiveprojection%ROWTYPE;
        attempt_row archival_archiveattempt%ROWTYPE;
        reported_attempt_row archival_archiveattempt%ROWTYPE;
        receipt_conflict boolean;
BEGIN
  SELECT * INTO projection_row FROM archival_archiveprojection WHERE id=NEW.lookup_projection_id;
  SELECT * INTO attempt_row FROM archival_archiveattempt WHERE id=NEW.source_attempt_id;
  SELECT * INTO reported_attempt_row FROM archival_archiveattempt
   WHERE id=NEW.reported_attempt_id;
  INSERT INTO archival_archivereceiptidentity
    (receiver_id,receiver_version,target_receipt_id,evidence_fingerprint)
    VALUES (NEW.receiver_id,NEW.receiver_version,NEW.target_receipt_id,NEW.evidence_fingerprint)
    ON CONFLICT (receiver_id,receiver_version,target_receipt_id) DO NOTHING;
  SELECT anchor.evidence_fingerprint IS DISTINCT FROM NEW.evidence_fingerprint
    INTO receipt_conflict FROM archival_archivereceiptidentity anchor
   WHERE anchor.receiver_id=NEW.receiver_id AND anchor.receiver_version=NEW.receiver_version
     AND anchor.target_receipt_id=NEW.target_receipt_id FOR UPDATE;
  IF projection_row.id IS NULL
     OR projection_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR NEW.receiver_id <> 'synthetic-archive' OR NEW.receiver_version <> 'v1'
     OR NEW.reported_organization_id IS DISTINCT FROM projection_row.organization_id
     OR NEW.reported_encounter_id IS DISTINCT FROM projection_row.encounter_id
     OR NEW.reported_projection_id IS DISTINCT FROM projection_row.id
     OR NEW.reported_projection_version IS DISTINCT FROM projection_row.version
     OR NEW.reported_digest IS DISTINCT FROM projection_row.projection_digest
     OR NEW.reported_byte_length IS DISTINCT FROM projection_row.byte_length
     OR NEW.received_bytes IS DISTINCT FROM projection_row.projection_bytes
     OR octet_length(NEW.received_bytes) IS DISTINCT FROM projection_row.byte_length
     OR NEW.evidence_fingerprint !~ '^[0-9a-f]{64}$'
     OR receipt_conflict
     OR (attempt_row.id IS NOT NULL AND (
       attempt_row.organization_id IS DISTINCT FROM NEW.organization_id
       OR attempt_row.projection_id IS DISTINCT FROM projection_row.id))
     OR (NEW.reported_attempt_id IS NOT NULL AND (
       reported_attempt_row.id IS NULL
       OR reported_attempt_row.organization_id IS DISTINCT FROM NEW.organization_id
       OR reported_attempt_row.projection_id IS DISTINCT FROM projection_row.id
       OR reported_attempt_row.receiver_id IS DISTINCT FROM NEW.receiver_id
       OR reported_attempt_row.receiver_version IS DISTINCT FROM NEW.receiver_version
     )) THEN
    NEW.observed_state := 'conflict';
    NEW.conflict_reason := CASE WHEN receipt_conflict
      THEN 'archive_receipt_identity_conflict' ELSE 'archive_binding_mismatch' END;
  ELSE
    NEW.observed_state := 'verified';
    NEW.conflict_reason := '';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER archival_observation_admission
  BEFORE INSERT ON archival_archivereadbackobservation
  FOR EACH ROW EXECUTE FUNCTION archival_f4_observation_guard();

CREATE FUNCTION archival_f4_outcome_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE attempt_row archival_archiveattempt%ROWTYPE;
        observation_row archival_archivereadbackobservation%ROWTYPE;
BEGIN
  SELECT * INTO attempt_row FROM archival_archiveattempt WHERE id=NEW.attempt_id;
  IF attempt_row.id IS NULL OR attempt_row.organization_id IS DISTINCT FROM NEW.organization_id THEN
    RAISE EXCEPTION 'archive outcome attempt mismatch' USING ERRCODE='23514';
  END IF;
  IF NEW.kind='pre_write_failed' AND attempt_row.possible_write THEN
    RAISE EXCEPTION 'possible archive write cannot be pre-write failure' USING ERRCODE='23514';
  ELSIF NEW.kind IN ('target_rejected','target_confirmed','unknown')
        AND NOT attempt_row.possible_write THEN
    RAISE EXCEPTION 'archive write outcome requires possible-write marker' USING ERRCODE='23514';
  END IF;
  IF NEW.readback_observation_id IS NOT NULL THEN
    SELECT * INTO observation_row FROM archival_archivereadbackobservation
     WHERE id=NEW.readback_observation_id;
    IF observation_row.id IS NULL
       OR observation_row.organization_id IS DISTINCT FROM NEW.organization_id
       OR observation_row.lookup_projection_id IS DISTINCT FROM attempt_row.projection_id
       OR observation_row.receiver_id IS DISTINCT FROM attempt_row.receiver_id
       OR observation_row.receiver_version IS DISTINCT FROM attempt_row.receiver_version
       OR observation_row.reported_projection_id IS DISTINCT FROM attempt_row.projection_id
       OR observation_row.reported_projection_version IS DISTINCT FROM (
         SELECT version FROM archival_archiveprojection WHERE id=attempt_row.projection_id
       )
       OR observation_row.reported_digest IS DISTINCT FROM attempt_row.projection_digest
       OR observation_row.reported_byte_length IS DISTINCT FROM attempt_row.byte_length THEN
      RAISE EXCEPTION 'archive outcome readback does not match attempt projection'
        USING ERRCODE='23514';
    END IF;
  END IF;
  IF NEW.kind='target_confirmed' AND (
      NEW.readback_observation_id IS NULL
      OR observation_row.observed_state <> 'verified') THEN
    RAISE EXCEPTION 'archive confirmation requires exact verified readback'
      USING ERRCODE='23514';
  ELSIF NEW.readback_observation_id IS NOT NULL
        AND NEW.kind NOT IN ('target_confirmed','unknown') THEN
    RAISE EXCEPTION 'archive outcome readback shape invalid' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER archival_outcome_admission
  BEFORE INSERT ON archival_archiveattemptoutcome
  FOR EACH ROW EXECUTE FUNCTION archival_f4_outcome_guard();
"""


REVERSE_SQL = r"""
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM archival_archiveprojection)
     OR EXISTS (SELECT 1 FROM archival_archiveattempt)
     OR EXISTS (SELECT 1 FROM archival_archivecommandreceipt) THEN
    RAISE EXCEPTION 'populated F4 archive rollback is unsupported; repair forward or restore a consistent pre-F4 backup'
      USING ERRCODE='55000';
  END IF;
END;
$$;
DROP TRIGGER IF EXISTS archival_outcome_admission ON archival_archiveattemptoutcome;
DROP TRIGGER IF EXISTS archival_observation_admission ON archival_archivereadbackobservation;
DROP TRIGGER IF EXISTS archival_attempt_admission ON archival_archiveattempt;
DROP TRIGGER IF EXISTS archival_item_admission ON archival_archivebatchitem;
DROP TRIGGER IF EXISTS archival_work_guard ON archival_archivework;
DROP TRIGGER IF EXISTS archival_authorization_admission ON archival_archiveauthorization;
DROP TRIGGER IF EXISTS archival_receipt_admission ON archival_archivecommandreceipt;
DROP TRIGGER IF EXISTS archival_head_guard ON archival_archivehead;
DROP TRIGGER IF EXISTS archival_projection_admission ON archival_archiveprojection;
DROP TRIGGER IF EXISTS archival_receiptidentity_immutable ON archival_archivereceiptidentity;
DO $$ DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'archival_archiveprojection','archival_archivebatch',
    'archival_archivecommandreceipt','archival_archiveauthorization',
    'archival_archivebatchitem','archival_archiveattempt',
    'archival_archivereadbackobservation','archival_archiveattemptoutcome'
  ] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I', table_name || '_immutable', table_name);
  END LOOP;
END;
$$;
DROP FUNCTION IF EXISTS archival_f4_outcome_guard();
DROP FUNCTION IF EXISTS archival_f4_observation_guard();
DROP FUNCTION IF EXISTS archival_f4_attempt_guard();
DROP FUNCTION IF EXISTS archival_f4_item_guard();
DROP FUNCTION IF EXISTS archival_f4_work_guard();
DROP FUNCTION IF EXISTS archival_f4_authorization_guard();
DROP FUNCTION IF EXISTS archival_f4_receipt_guard();
DROP FUNCTION IF EXISTS archival_f4_head_guard();
DROP FUNCTION IF EXISTS archival_f4_projection_guard();
DROP TABLE IF EXISTS archival_archivereceiptidentity;
DROP FUNCTION IF EXISTS archival_f4_reject_history_change();
"""


class Migration(migrations.Migration):
    dependencies = [("archival", "0001_initial")]
    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
