from django.db import migrations


FORWARD_SQL = """
ALTER TABLE sources_delivery ADD CONSTRAINT sources_delivery_artifact_same_org_fk
  FOREIGN KEY (organization_id, artifact_id) REFERENCES sources_artifact (organization_id, id)
  DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE sources_delivery ADD CONSTRAINT sources_delivery_supersedes_same_org_fk
  FOREIGN KEY (organization_id, supersedes_id) REFERENCES sources_delivery (organization_id, id)
  DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE sources_parseresult ADD CONSTRAINT sources_result_delivery_same_org_fk
  FOREIGN KEY (organization_id, delivery_id) REFERENCES sources_delivery (organization_id, id)
  DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE sources_parseattempt ADD CONSTRAINT sources_attempt_delivery_same_org_fk
  FOREIGN KEY (organization_id, delivery_id) REFERENCES sources_delivery (organization_id, id)
  DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE sources_observation ADD CONSTRAINT sources_observation_result_same_org_fk
  FOREIGN KEY (organization_id, parse_result_id) REFERENCES sources_parseresult (organization_id, id)
  DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE sources_artifact ADD CONSTRAINT sources_artifact_positive_length_ck CHECK (byte_length > 0);
ALTER TABLE sources_delivery ADD CONSTRAINT sources_delivery_namespace_nonblank_ck CHECK (char_length(btrim(source_namespace)) > 0);
ALTER TABLE sources_delivery ADD CONSTRAINT sources_delivery_key_nonblank_ck CHECK (char_length(btrim(source_key)) > 0);
ALTER TABLE sources_observation ADD CONSTRAINT sources_observation_positive_row_ck CHECK (row_ordinal > 0);
ALTER TABLE sources_parseattempt ADD CONSTRAINT sources_attempt_time_order_ck CHECK (ended_at >= started_at);

CREATE FUNCTION medicafe_reject_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'immutable F1 row: %', TG_TABLE_NAME USING ERRCODE = '55000';
END;
$$;
CREATE TRIGGER sources_artifact_immutable BEFORE UPDATE ON sources_artifact
  FOR EACH ROW EXECUTE FUNCTION medicafe_reject_update();
CREATE TRIGGER sources_delivery_immutable BEFORE UPDATE ON sources_delivery
  FOR EACH ROW EXECUTE FUNCTION medicafe_reject_update();
CREATE TRIGGER sources_result_immutable BEFORE UPDATE ON sources_parseresult
  FOR EACH ROW EXECUTE FUNCTION medicafe_reject_update();
CREATE TRIGGER sources_attempt_immutable BEFORE UPDATE ON sources_parseattempt
  FOR EACH ROW EXECUTE FUNCTION medicafe_reject_update();
CREATE TRIGGER sources_observation_immutable BEFORE UPDATE ON sources_observation
  FOR EACH ROW EXECUTE FUNCTION medicafe_reject_update();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS sources_observation_immutable ON sources_observation;
DROP TRIGGER IF EXISTS sources_attempt_immutable ON sources_parseattempt;
DROP TRIGGER IF EXISTS sources_result_immutable ON sources_parseresult;
DROP TRIGGER IF EXISTS sources_delivery_immutable ON sources_delivery;
DROP TRIGGER IF EXISTS sources_artifact_immutable ON sources_artifact;
DROP FUNCTION IF EXISTS medicafe_reject_update();
ALTER TABLE sources_observation DROP CONSTRAINT IF EXISTS sources_observation_positive_row_ck;
ALTER TABLE sources_artifact DROP CONSTRAINT IF EXISTS sources_artifact_positive_length_ck;
ALTER TABLE sources_delivery DROP CONSTRAINT IF EXISTS sources_delivery_namespace_nonblank_ck;
ALTER TABLE sources_delivery DROP CONSTRAINT IF EXISTS sources_delivery_key_nonblank_ck;
ALTER TABLE sources_parseattempt DROP CONSTRAINT IF EXISTS sources_attempt_time_order_ck;
ALTER TABLE sources_observation DROP CONSTRAINT IF EXISTS sources_observation_result_same_org_fk;
ALTER TABLE sources_parseattempt DROP CONSTRAINT IF EXISTS sources_attempt_delivery_same_org_fk;
ALTER TABLE sources_parseresult DROP CONSTRAINT IF EXISTS sources_result_delivery_same_org_fk;
ALTER TABLE sources_delivery DROP CONSTRAINT IF EXISTS sources_delivery_supersedes_same_org_fk;
ALTER TABLE sources_delivery DROP CONSTRAINT IF EXISTS sources_delivery_artifact_same_org_fk;
"""


class Migration(migrations.Migration):
    dependencies = [("sources", "0001_initial")]
    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
