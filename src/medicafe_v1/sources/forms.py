import uuid

from django import forms


class UploadForm(forms.Form):
    source_namespace = forms.CharField(max_length=100, initial="synthetic-demo")
    source_key = forms.UUIDField(widget=forms.HiddenInput)
    source_file = forms.FileField(label="Synthetic CSV or DOCX")
    supersedes_id = forms.UUIDField(required=False, label="Corrects delivery ID (optional)")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound and not self.initial.get("source_key"):
            self.initial["source_key"] = uuid.uuid4()


class ResolutionForm(forms.Form):
    request_uuid = forms.UUIDField(widget=forms.HiddenInput)
    mode = forms.ChoiceField(choices=[("attach", "Attach existing encounter"), ("create", "Create patient and encounter")])
    reason = forms.CharField(max_length=500)
    patient_id = forms.UUIDField(required=False)
    encounter_id = forms.UUIDField(required=False)
    display_name = forms.CharField(max_length=200, required=False)
    alias_namespace = forms.CharField(max_length=100, required=False, initial="synthetic-patient-ref")
    alias_value = forms.CharField(max_length=200, required=False)
    service_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound and not self.initial.get("request_uuid"):
            self.initial["request_uuid"] = uuid.uuid4()

