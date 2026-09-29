import uuid

from django import forms


class RequestTargetForm(forms.Form):
    request_uuid = forms.UUIDField(widget=forms.HiddenInput)
    target_id = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound and not self.initial.get("request_uuid"):
            self.initial["request_uuid"] = uuid.uuid4()


class CaptureForm(RequestTargetForm):
    expected_projection_id = forms.UUIDField(required=False, widget=forms.HiddenInput)


class QueueForm(RequestTargetForm):
    pass


class RetryForm(RequestTargetForm):
    expected_attempt_id = forms.UUIDField(widget=forms.HiddenInput)


class ReconcileForm(forms.Form):
    target_id = forms.UUIDField(widget=forms.HiddenInput)
