from django.db import migrations


FORWARD_SQL = """
ALTER TABLE records_patientalias ADD CONSTRAINT records_alias_patient_same_org_fk
  FOREIGN KEY (organization_id, patient_id) REFERENCES records_patient (organization_id, id)
  DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE records_encounter ADD CONSTRAINT records_encounter_patient_same_org_fk
  FOREIGN KEY (organization_id, patient_id) REFERENCES records_patient (organization_id, id)
  DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE records_identitydecision ADD CONSTRAINT records_decision_observation_same_org_fk
  FOREIGN KEY (organization_id, observation_id) REFERENCES sources_observation (organization_id, id)
  DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE records_identitydecision ADD CONSTRAINT records_decision_patient_same_org_fk
  FOREIGN KEY (organization_id, patient_id) REFERENCES records_patient (organization_id, id)
  DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE records_identitydecision ADD CONSTRAINT records_decision_encounter_same_org_fk
  FOREIGN KEY (organization_id, encounter_id) REFERENCES records_encounter (organization_id, id)
  DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE records_identitydecision ADD CONSTRAINT records_decision_encounter_patient_fk
  FOREIGN KEY (organization_id, patient_id, encounter_id)
  REFERENCES records_encounter (organization_id, patient_id, id)
  DEFERRABLE INITIALLY DEFERRED;
CREATE TRIGGER records_decision_immutable BEFORE UPDATE OR DELETE ON records_identitydecision
  FOR EACH ROW EXECUTE FUNCTION medicafe_reject_update();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS records_decision_immutable ON records_identitydecision;
ALTER TABLE records_identitydecision DROP CONSTRAINT IF EXISTS records_decision_encounter_patient_fk;
ALTER TABLE records_identitydecision DROP CONSTRAINT IF EXISTS records_decision_encounter_same_org_fk;
ALTER TABLE records_identitydecision DROP CONSTRAINT IF EXISTS records_decision_patient_same_org_fk;
ALTER TABLE records_identitydecision DROP CONSTRAINT IF EXISTS records_decision_observation_same_org_fk;
ALTER TABLE records_encounter DROP CONSTRAINT IF EXISTS records_encounter_patient_same_org_fk;
ALTER TABLE records_patientalias DROP CONSTRAINT IF EXISTS records_alias_patient_same_org_fk;
"""


class Migration(migrations.Migration):
    dependencies = [("records", "0001_initial"), ("sources", "0002_tenant_integrity")]
    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
