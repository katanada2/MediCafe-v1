from django.db import migrations


FORWARD_SQL = r"""
CREATE FUNCTION outcomes_f4_reject_history_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'F4 accepted history is immutable' USING ERRCODE='55000';
END;
$$;

DO $$ DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'outcomes_inboundattempt','outcomes_inboundcandidate',
    'outcomes_inboundcandidateline','outcomes_inboundconflict',
    'outcomes_acceptedevent','outcomes_acceptedeventevidence',
    'outcomes_chargebasis','outcomes_postingbatch','outcomes_postingentry',
    'outcomes_outcomescommandreceipt'
  ] LOOP
    EXECUTE format(
      'CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %I '
      'FOR EACH ROW EXECUTE FUNCTION outcomes_f4_reject_history_change()',
      table_name || '_immutable', table_name
    );
  END LOOP;
END;
$$;

CREATE FUNCTION outcomes_f4_account_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'F4 financial account cannot be deleted' USING ERRCODE='55000';
  END IF;
  IF ROW(NEW.id,NEW.organization_id,NEW.claim_revision_id,NEW.currency,
         NEW.original_charge,NEW.created_at)
     IS DISTINCT FROM
     ROW(OLD.id,OLD.organization_id,OLD.claim_revision_id,OLD.currency,
         OLD.original_charge,OLD.created_at)
     OR NEW.posting_generation <= OLD.posting_generation THEN
    RAISE EXCEPTION 'F4 financial account identity and charge are immutable' USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER outcomes_financialaccount_guard
  BEFORE UPDATE OR DELETE ON outcomes_financialaccount
  FOR EACH ROW EXECUTE FUNCTION outcomes_f4_account_guard();

CREATE FUNCTION outcomes_f4_attempt_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE delivery_row sources_delivery%ROWTYPE;
BEGIN
  SELECT * INTO delivery_row FROM sources_delivery WHERE id=NEW.delivery_id;
  IF delivery_row.id IS NULL
     OR delivery_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR NEW.ended_at < NEW.started_at THEN
    RAISE EXCEPTION 'inbound attempt delivery or terminal time mismatch' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER outcomes_attempt_admission
  BEFORE INSERT ON outcomes_inboundattempt
  FOR EACH ROW EXECUTE FUNCTION outcomes_f4_attempt_guard();

CREATE FUNCTION outcomes_f4_candidate_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE delivery_row sources_delivery%ROWTYPE;
BEGIN
  SELECT * INTO delivery_row FROM sources_delivery WHERE id=NEW.delivery_id;
  IF delivery_row.id IS NULL OR delivery_row.organization_id IS DISTINCT FROM NEW.organization_id THEN
    RAISE EXCEPTION 'inbound candidate delivery mismatch' USING ERRCODE='23514';
  END IF;
  IF NEW.semantic_digest !~ '^[0-9a-f]{64}$'
     OR octet_length(NEW.semantic_bytes)=0 THEN
    RAISE EXCEPTION 'inbound candidate semantic evidence invalid' USING ERRCODE='23514';
  END IF;
  IF NEW.kind='lifecycle' AND (
       (NEW.lifecycle_sequence=1 AND NEW.predecessor_event_id IS NOT NULL)
       OR (NEW.lifecycle_sequence>1 AND NEW.predecessor_event_id IS NULL)) THEN
    RAISE EXCEPTION 'lifecycle predecessor shape invalid' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER outcomes_candidate_admission
  BEFORE INSERT ON outcomes_inboundcandidate
  FOR EACH ROW EXECUTE FUNCTION outcomes_f4_candidate_guard();

CREATE FUNCTION outcomes_f4_candidate_line_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE candidate_row outcomes_inboundcandidate%ROWTYPE; matched integer;
BEGIN
  SELECT * INTO candidate_row FROM outcomes_inboundcandidate WHERE id=NEW.candidate_id;
  IF candidate_row.id IS NULL
     OR candidate_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR candidate_row.kind <> 'remittance' THEN
    RAISE EXCEPTION 'inbound candidate line mismatch' USING ERRCODE='23514';
  END IF;
  IF EXISTS (SELECT 1 FROM outcomes_inboundattempt attempt
      WHERE attempt.delivery_id=candidate_row.delivery_id
        AND attempt.interpreter_version=candidate_row.interpreter_version
        AND attempt.succeeded) THEN
    RAISE EXCEPTION 'inbound candidate lines are sealed after interpretation'
      USING ERRCODE='55000';
  END IF;
  SELECT count(*) INTO matched
    FROM jsonb_array_elements(candidate_row.normalized_content->'lines') item
   WHERE (item->>'line_ordinal')::integer=NEW.line_ordinal
     AND (item->>'paid_amount')::numeric=NEW.paid_amount
     AND (item->>'contractual_adjustment')::numeric=NEW.contractual_adjustment;
  IF matched <> 1 THEN
    RAISE EXCEPTION 'candidate line is not an exact retained semantic component'
      USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER outcomes_candidate_line_admission
  BEFORE INSERT ON outcomes_inboundcandidateline
  FOR EACH ROW EXECUTE FUNCTION outcomes_f4_candidate_line_guard();

CREATE FUNCTION outcomes_f4_candidate_complete_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE expected_count integer; actual_count integer; mismatch_count integer;
BEGIN
  IF NEW.kind='lifecycle' THEN
    IF EXISTS (SELECT 1 FROM outcomes_inboundcandidateline WHERE candidate_id=NEW.id) THEN
      RAISE EXCEPTION 'lifecycle candidate cannot have remittance lines' USING ERRCODE='23514';
    END IF;
  ELSE
    expected_count := jsonb_array_length(NEW.normalized_content->'lines');
    SELECT count(*) INTO actual_count FROM outcomes_inboundcandidateline WHERE candidate_id=NEW.id;
    SELECT count(*) INTO mismatch_count
      FROM outcomes_inboundcandidateline line
     WHERE line.candidate_id=NEW.id AND NOT EXISTS (
       SELECT 1 FROM jsonb_array_elements(NEW.normalized_content->'lines') item
        WHERE (item->>'line_ordinal')::integer=line.line_ordinal
          AND (item->>'paid_amount')::numeric=line.paid_amount
          AND (item->>'contractual_adjustment')::numeric=line.contractual_adjustment
     );
    IF actual_count IS DISTINCT FROM expected_count OR mismatch_count <> 0 THEN
      RAISE EXCEPTION 'candidate line relation is incomplete or mismatched' USING ERRCODE='23514';
    END IF;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM outcomes_inboundattempt attempt
      WHERE attempt.delivery_id=NEW.delivery_id
        AND attempt.interpreter_version=NEW.interpreter_version
        AND attempt.succeeded) THEN
    RAISE EXCEPTION 'successful candidate requires terminal interpretation attempt'
      USING ERRCODE='23514';
  END IF;
  RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER outcomes_candidate_complete
  AFTER INSERT ON outcomes_inboundcandidate DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION outcomes_f4_candidate_complete_guard();

CREATE FUNCTION outcomes_f4_conflict_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE left_row outcomes_inboundcandidate%ROWTYPE; right_row outcomes_inboundcandidate%ROWTYPE;
BEGIN
  SELECT * INTO left_row FROM outcomes_inboundcandidate WHERE id=NEW.existing_candidate_id;
  SELECT * INTO right_row FROM outcomes_inboundcandidate WHERE id=NEW.conflicting_candidate_id;
  IF left_row.id IS NULL OR right_row.id IS NULL OR left_row.id=right_row.id
     OR left_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR right_row.organization_id IS DISTINCT FROM NEW.organization_id THEN
    RAISE EXCEPTION 'inbound conflict evidence mismatch' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER outcomes_conflict_admission
  BEFORE INSERT ON outcomes_inboundconflict
  FOR EACH ROW EXECUTE FUNCTION outcomes_f4_conflict_guard();

CREATE FUNCTION outcomes_f4_event_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE candidate_row outcomes_inboundcandidate%ROWTYPE;
        intent_row claims_deliveryintent%ROWTYPE;
        observation_row claims_receiverobservation%ROWTYPE;
        predecessor_row outcomes_acceptedevent%ROWTYPE;
BEGIN
  SELECT * INTO candidate_row FROM outcomes_inboundcandidate WHERE id=NEW.primary_candidate_id;
  SELECT * INTO intent_row FROM claims_deliveryintent WHERE id=NEW.intent_id;
  SELECT * INTO observation_row FROM claims_receiverobservation WHERE id=NEW.receiver_observation_id;
  IF candidate_row.id IS NULL OR intent_row.id IS NULL OR observation_row.id IS NULL
     OR candidate_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR candidate_row.kind IS DISTINCT FROM NEW.kind
     OR candidate_row.sender_id IS DISTINCT FROM NEW.sender_id
     OR candidate_row.event_id IS DISTINCT FROM NEW.event_id
     OR candidate_row.semantic_digest IS DISTINCT FROM NEW.semantic_digest
     OR candidate_row.intent_id IS DISTINCT FROM NEW.intent_id
     OR candidate_row.claim_revision_id IS DISTINCT FROM NEW.claim_revision_id
     OR candidate_row.receiver_receipt_id IS DISTINCT FROM NEW.receiver_receipt_id
     OR intent_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR intent_row.claim_revision_id IS DISTINCT FROM NEW.claim_revision_id
     OR observation_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR observation_row.intent_id IS DISTINCT FROM NEW.intent_id
     OR observation_row.receipt_id IS DISTINCT FROM NEW.receiver_receipt_id
     OR observation_row.evidence_fingerprint IS DISTINCT FROM NEW.receiver_evidence_fingerprint
     OR observation_row.observed_state <> 'accepted' OR NOT observation_row.binding_valid THEN
    RAISE EXCEPTION 'accepted event candidate or delivery evidence mismatch' USING ERRCODE='23514';
  END IF;
  IF NEW.kind='lifecycle' THEN
    IF NEW.lifecycle_sequence IS DISTINCT FROM candidate_row.lifecycle_sequence
       OR NEW.predecessor_event_id IS DISTINCT FROM candidate_row.predecessor_event_id
       OR NEW.lifecycle_status IS DISTINCT FROM candidate_row.lifecycle_status THEN
      RAISE EXCEPTION 'accepted lifecycle event differs from retained candidate'
        USING ERRCODE='23514';
    END IF;
    IF NEW.lifecycle_sequence=1 AND NEW.predecessor_event_id IS NOT NULL THEN
      RAISE EXCEPTION 'first lifecycle event cannot name predecessor' USING ERRCODE='23514';
    ELSIF NEW.lifecycle_sequence>1 THEN
      SELECT * INTO predecessor_row FROM outcomes_acceptedevent
       WHERE organization_id=NEW.organization_id AND sender_id=NEW.sender_id
         AND kind='lifecycle' AND intent_id=NEW.intent_id
         AND lifecycle_sequence=NEW.lifecycle_sequence-1
         AND event_id=NEW.predecessor_event_id;
      IF predecessor_row.id IS NULL THEN
        RAISE EXCEPTION 'lifecycle predecessor missing or mismatched' USING ERRCODE='23514';
      END IF;
    END IF;
  ELSIF NEW.kind='remittance' AND (
      NEW.lifecycle_sequence IS NOT NULL OR NEW.predecessor_event_id IS NOT NULL
      OR NEW.lifecycle_status <> '') THEN
    RAISE EXCEPTION 'remittance event has lifecycle fields' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER outcomes_event_admission
  BEFORE INSERT ON outcomes_acceptedevent
  FOR EACH ROW EXECUTE FUNCTION outcomes_f4_event_guard();

CREATE FUNCTION outcomes_f4_evidence_link_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE event_row outcomes_acceptedevent%ROWTYPE; candidate_row outcomes_inboundcandidate%ROWTYPE;
BEGIN
  SELECT * INTO event_row FROM outcomes_acceptedevent WHERE id=NEW.event_id;
  SELECT * INTO candidate_row FROM outcomes_inboundcandidate WHERE id=NEW.candidate_id;
  IF event_row.id IS NULL OR candidate_row.id IS NULL
     OR event_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR candidate_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR event_row.sender_id IS DISTINCT FROM candidate_row.sender_id
     OR event_row.kind IS DISTINCT FROM candidate_row.kind
     OR event_row.event_id IS DISTINCT FROM candidate_row.event_id
     OR event_row.semantic_digest IS DISTINCT FROM candidate_row.semantic_digest THEN
    RAISE EXCEPTION 'accepted event evidence mismatch' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER outcomes_evidence_link_admission
  BEFORE INSERT ON outcomes_acceptedeventevidence
  FOR EACH ROW EXECUTE FUNCTION outcomes_f4_evidence_link_guard();

CREATE FUNCTION outcomes_f4_account_admission() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE revision_row claims_claimrevision%ROWTYPE;
BEGIN
  SELECT * INTO revision_row FROM claims_claimrevision WHERE id=NEW.claim_revision_id;
  IF revision_row.id IS NULL OR revision_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR revision_row.currency IS DISTINCT FROM NEW.currency
     OR revision_row.total_amount IS DISTINCT FROM NEW.original_charge
     OR NEW.currency <> 'USD' THEN
    RAISE EXCEPTION 'financial account charge or revision mismatch' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER outcomes_account_admission
  BEFORE INSERT ON outcomes_financialaccount
  FOR EACH ROW EXECUTE FUNCTION outcomes_f4_account_admission();

CREATE FUNCTION outcomes_f4_basis_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE account_row outcomes_financialaccount%ROWTYPE; line_row claims_claimline%ROWTYPE;
BEGIN
  SELECT * INTO account_row FROM outcomes_financialaccount WHERE id=NEW.account_id;
  SELECT * INTO line_row FROM claims_claimline WHERE id=NEW.claim_line_id;
  IF account_row.id IS NULL OR line_row.id IS NULL
     OR account_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR line_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR line_row.claim_revision_id IS DISTINCT FROM account_row.claim_revision_id
     OR line_row.ordinal IS DISTINCT FROM NEW.line_ordinal
     OR line_row.line_amount IS DISTINCT FROM NEW.original_charge
     OR line_row.currency IS DISTINCT FROM NEW.currency
     OR account_row.currency IS DISTINCT FROM NEW.currency THEN
    RAISE EXCEPTION 'charge basis line or account mismatch' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER outcomes_basis_admission
  BEFORE INSERT ON outcomes_chargebasis
  FOR EACH ROW EXECUTE FUNCTION outcomes_f4_basis_guard();

CREATE FUNCTION outcomes_f4_batch_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE event_row outcomes_acceptedevent%ROWTYPE; account_row outcomes_financialaccount%ROWTYPE;
BEGIN
  SELECT * INTO event_row FROM outcomes_acceptedevent WHERE id=NEW.event_id;
  SELECT * INTO account_row FROM outcomes_financialaccount WHERE id=NEW.account_id;
  IF event_row.id IS NULL OR account_row.id IS NULL OR event_row.kind <> 'remittance'
     OR event_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR account_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR event_row.claim_revision_id IS DISTINCT FROM account_row.claim_revision_id THEN
    RAISE EXCEPTION 'posting batch event or account mismatch' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER outcomes_batch_admission
  BEFORE INSERT ON outcomes_postingbatch
  FOR EACH ROW EXECUTE FUNCTION outcomes_f4_batch_guard();

CREATE FUNCTION outcomes_f4_entry_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE batch_row outcomes_postingbatch%ROWTYPE; event_row outcomes_acceptedevent%ROWTYPE;
        account_row outcomes_financialaccount%ROWTYPE; basis_row outcomes_chargebasis%ROWTYPE;
        candidate_line outcomes_inboundcandidateline%ROWTYPE; allocated numeric; expected_amount numeric;
BEGIN
  UPDATE outcomes_financialaccount
     SET posting_generation=posting_generation+1
   WHERE id=NEW.account_id
   RETURNING * INTO account_row;
  SELECT * INTO batch_row FROM outcomes_postingbatch WHERE id=NEW.batch_id;
  SELECT * INTO event_row FROM outcomes_acceptedevent WHERE id=NEW.event_id;
  SELECT * INTO basis_row FROM outcomes_chargebasis WHERE id=NEW.charge_basis_id;
  IF account_row.id IS NULL OR batch_row.id IS NULL OR event_row.id IS NULL OR basis_row.id IS NULL
     OR account_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR batch_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR event_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR basis_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR batch_row.account_id IS DISTINCT FROM NEW.account_id
     OR batch_row.event_id IS DISTINCT FROM NEW.event_id
     OR basis_row.account_id IS DISTINCT FROM NEW.account_id
     OR basis_row.claim_line_id IS DISTINCT FROM NEW.claim_line_id
     OR event_row.claim_revision_id IS DISTINCT FROM account_row.claim_revision_id
     OR NEW.currency IS DISTINCT FROM account_row.currency
     OR NEW.currency IS DISTINCT FROM basis_row.currency THEN
    RAISE EXCEPTION 'posting entry relationship mismatch' USING ERRCODE='23514';
  END IF;
  IF NEW.kind NOT IN ('payer_reported_payment','contractual_adjustment') THEN
    RAISE EXCEPTION 'posting entry kind unsupported' USING ERRCODE='23514';
  END IF;
  SELECT line.* INTO candidate_line
    FROM outcomes_inboundcandidateline line
   WHERE line.candidate_id=event_row.primary_candidate_id
     AND line.line_ordinal=basis_row.line_ordinal;
  expected_amount := CASE WHEN NEW.kind='payer_reported_payment'
    THEN candidate_line.paid_amount ELSE candidate_line.contractual_adjustment END;
  IF candidate_line.id IS NULL OR expected_amount <= 0
     OR NEW.amount IS DISTINCT FROM expected_amount THEN
    RAISE EXCEPTION 'posting entry is not an exact retained candidate component'
      USING ERRCODE='23514';
  END IF;
  SELECT COALESCE(sum(amount),0) INTO allocated
    FROM outcomes_postingentry WHERE charge_basis_id=NEW.charge_basis_id;
  IF allocated + NEW.amount > basis_row.original_charge THEN
    RAISE EXCEPTION 'overallocated_line' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER outcomes_entry_admission
  BEFORE INSERT ON outcomes_postingentry
  FOR EACH ROW EXECUTE FUNCTION outcomes_f4_entry_guard();

CREATE FUNCTION outcomes_f4_batch_complete_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE mismatch_count integer;
BEGIN
  SELECT count(*) INTO mismatch_count
    FROM outcomes_inboundcandidateline line
    JOIN outcomes_acceptedevent event ON event.primary_candidate_id=line.candidate_id
   WHERE event.id=NEW.event_id AND (
     (line.paid_amount > 0 AND NOT EXISTS (
       SELECT 1 FROM outcomes_postingentry entry
        WHERE entry.batch_id=NEW.id AND entry.claim_line_id=(
          SELECT basis.claim_line_id FROM outcomes_chargebasis basis
           WHERE basis.account_id=NEW.account_id AND basis.line_ordinal=line.line_ordinal)
          AND entry.kind='payer_reported_payment' AND entry.amount=line.paid_amount))
     OR (line.paid_amount = 0 AND EXISTS (
       SELECT 1 FROM outcomes_postingentry entry
        JOIN outcomes_chargebasis basis ON basis.id=entry.charge_basis_id
        WHERE entry.batch_id=NEW.id AND basis.line_ordinal=line.line_ordinal
          AND entry.kind='payer_reported_payment'))
     OR (line.contractual_adjustment > 0 AND NOT EXISTS (
       SELECT 1 FROM outcomes_postingentry entry
        WHERE entry.batch_id=NEW.id AND entry.claim_line_id=(
          SELECT basis.claim_line_id FROM outcomes_chargebasis basis
           WHERE basis.account_id=NEW.account_id AND basis.line_ordinal=line.line_ordinal)
          AND entry.kind='contractual_adjustment'
          AND entry.amount=line.contractual_adjustment))
     OR (line.contractual_adjustment = 0 AND EXISTS (
       SELECT 1 FROM outcomes_postingentry entry
        JOIN outcomes_chargebasis basis ON basis.id=entry.charge_basis_id
        WHERE entry.batch_id=NEW.id AND basis.line_ordinal=line.line_ordinal
          AND entry.kind='contractual_adjustment'))
   );
  IF mismatch_count <> 0 OR EXISTS (
    SELECT 1 FROM outcomes_postingentry entry
     WHERE entry.batch_id=NEW.id AND NOT EXISTS (
       SELECT 1 FROM outcomes_inboundcandidateline line
       JOIN outcomes_acceptedevent event ON event.primary_candidate_id=line.candidate_id
       JOIN outcomes_chargebasis basis ON basis.account_id=NEW.account_id
        AND basis.line_ordinal=line.line_ordinal
       WHERE event.id=NEW.event_id AND basis.claim_line_id=entry.claim_line_id
     )
  ) THEN
    RAISE EXCEPTION 'posting batch is incomplete or contains extra entries' USING ERRCODE='23514';
  END IF;
  RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER outcomes_batch_complete
  AFTER INSERT ON outcomes_postingbatch DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION outcomes_f4_batch_complete_guard();

CREATE FUNCTION outcomes_f4_receipt_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE candidate_row outcomes_inboundcandidate%ROWTYPE; event_row outcomes_acceptedevent%ROWTYPE;
        batch_row outcomes_postingbatch%ROWTYPE;
BEGIN
  SELECT * INTO candidate_row FROM outcomes_inboundcandidate WHERE id=NEW.target_candidate_id;
  SELECT * INTO event_row FROM outcomes_acceptedevent WHERE id=NEW.result_event_id;
  IF candidate_row.id IS NULL OR event_row.id IS NULL
     OR candidate_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR event_row.organization_id IS DISTINCT FROM NEW.organization_id
     OR candidate_row.intent_id IS DISTINCT FROM NEW.target_intent_id
     OR event_row.event_id IS DISTINCT FROM candidate_row.event_id
     OR event_row.semantic_digest IS DISTINCT FROM candidate_row.semantic_digest
     OR NEW.intent_digest !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'outcomes command receipt result mismatch' USING ERRCODE='23514';
  END IF;
  IF NEW.command_kind='post_remittance' THEN
    IF candidate_row.kind <> 'remittance' OR event_row.kind <> 'remittance' THEN
      RAISE EXCEPTION 'post remittance receipt requires remittance result' USING ERRCODE='23514';
    END IF;
    SELECT * INTO batch_row FROM outcomes_postingbatch WHERE id=NEW.result_batch_id;
    IF batch_row.id IS NULL OR batch_row.event_id IS DISTINCT FROM event_row.id THEN
      RAISE EXCEPTION 'remittance receipt batch mismatch' USING ERRCODE='23514';
    END IF;
  ELSIF NEW.command_kind='accept_lifecycle' THEN
    IF candidate_row.kind <> 'lifecycle' OR event_row.kind <> 'lifecycle'
       OR NEW.result_batch_id IS NOT NULL THEN
      RAISE EXCEPTION 'lifecycle receipt requires lifecycle result without batch' USING ERRCODE='23514';
    END IF;
  ELSIF NEW.command_kind NOT IN ('accept_lifecycle','post_remittance') THEN
    RAISE EXCEPTION 'unsupported outcomes command receipt kind' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE CONSTRAINT TRIGGER outcomes_receipt_admission
  AFTER INSERT ON outcomes_outcomescommandreceipt DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION outcomes_f4_receipt_guard();
"""


REVERSE_SQL = r"""
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM outcomes_inboundattempt)
     OR EXISTS (SELECT 1 FROM outcomes_inboundcandidate)
     OR EXISTS (SELECT 1 FROM outcomes_acceptedevent)
     OR EXISTS (SELECT 1 FROM outcomes_financialaccount) THEN
    RAISE EXCEPTION 'populated F4 outcomes rollback is unsupported; repair forward or restore a consistent pre-F4 backup'
      USING ERRCODE='55000';
  END IF;
END;
$$;
DROP TRIGGER IF EXISTS outcomes_receipt_admission ON outcomes_outcomescommandreceipt;
DROP TRIGGER IF EXISTS outcomes_batch_complete ON outcomes_postingbatch;
DROP TRIGGER IF EXISTS outcomes_entry_admission ON outcomes_postingentry;
DROP TRIGGER IF EXISTS outcomes_batch_admission ON outcomes_postingbatch;
DROP TRIGGER IF EXISTS outcomes_basis_admission ON outcomes_chargebasis;
DROP TRIGGER IF EXISTS outcomes_account_admission ON outcomes_financialaccount;
DROP TRIGGER IF EXISTS outcomes_evidence_link_admission ON outcomes_acceptedeventevidence;
DROP TRIGGER IF EXISTS outcomes_event_admission ON outcomes_acceptedevent;
DROP TRIGGER IF EXISTS outcomes_conflict_admission ON outcomes_inboundconflict;
DROP TRIGGER IF EXISTS outcomes_candidate_line_admission ON outcomes_inboundcandidateline;
DROP TRIGGER IF EXISTS outcomes_candidate_complete ON outcomes_inboundcandidate;
DROP TRIGGER IF EXISTS outcomes_candidate_admission ON outcomes_inboundcandidate;
DROP TRIGGER IF EXISTS outcomes_attempt_admission ON outcomes_inboundattempt;
DROP TRIGGER IF EXISTS outcomes_financialaccount_guard ON outcomes_financialaccount;
DO $$ DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'outcomes_inboundattempt','outcomes_inboundcandidate',
    'outcomes_inboundcandidateline','outcomes_inboundconflict',
    'outcomes_acceptedevent','outcomes_acceptedeventevidence',
    'outcomes_chargebasis','outcomes_postingbatch','outcomes_postingentry',
    'outcomes_outcomescommandreceipt'
  ] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I', table_name || '_immutable', table_name);
  END LOOP;
END;
$$;
DROP FUNCTION IF EXISTS outcomes_f4_receipt_guard();
DROP FUNCTION IF EXISTS outcomes_f4_batch_complete_guard();
DROP FUNCTION IF EXISTS outcomes_f4_entry_guard();
DROP FUNCTION IF EXISTS outcomes_f4_batch_guard();
DROP FUNCTION IF EXISTS outcomes_f4_basis_guard();
DROP FUNCTION IF EXISTS outcomes_f4_account_admission();
DROP FUNCTION IF EXISTS outcomes_f4_evidence_link_guard();
DROP FUNCTION IF EXISTS outcomes_f4_event_guard();
DROP FUNCTION IF EXISTS outcomes_f4_conflict_guard();
DROP FUNCTION IF EXISTS outcomes_f4_candidate_line_guard();
DROP FUNCTION IF EXISTS outcomes_f4_candidate_complete_guard();
DROP FUNCTION IF EXISTS outcomes_f4_candidate_guard();
DROP FUNCTION IF EXISTS outcomes_f4_attempt_guard();
DROP FUNCTION IF EXISTS outcomes_f4_account_guard();
DROP FUNCTION IF EXISTS outcomes_f4_reject_history_change();
"""


class Migration(migrations.Migration):
    dependencies = [("outcomes", "0001_initial")]
    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
