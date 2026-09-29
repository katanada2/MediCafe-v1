import uuid

from django import forms


class TargetForm(forms.Form):
    target_id = forms.UUIDField(widget=forms.HiddenInput)


class InterpretForm(TargetForm):
    pass


class CandidateCommandForm(TargetForm):
    request_uuid = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound and not self.initial.get("request_uuid"):
            self.initial["request_uuid"] = uuid.uuid4()


class ReevaluateForm(TargetForm):
    pass
