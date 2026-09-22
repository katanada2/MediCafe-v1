import uuid

from django import forms


class RequestForm(forms.Form):
    request_uuid = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound and not self.initial.get("request_uuid"):
            self.initial["request_uuid"] = uuid.uuid4()


class ServiceAcceptForm(RequestForm):
    identity_decision_id = forms.ChoiceField(label="Resolved source observation")
    code = forms.ChoiceField(choices=[("SYN-A", "SYN-A"), ("SYN-B", "SYN-B")])
    units = forms.IntegerField(min_value=1, max_value=100)
    unit_amount = forms.DecimalField(min_value=0, max_value=9999.99, decimal_places=2)
    currency = forms.ChoiceField(choices=[("USD", "USD")])
    reason = forms.CharField(max_length=500)

    def __init__(self, *args, decision_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["identity_decision_id"].choices = decision_choices


class ServiceRevisionForm(RequestForm):
    expected_revision_id = forms.UUIDField(widget=forms.HiddenInput)
    identity_decision_id = forms.ChoiceField(label="Resolved evidence observation")
    disposition = forms.ChoiceField(choices=[("accepted", "Accepted"), ("excluded", "Excluded")])
    code = forms.ChoiceField(choices=[("SYN-A", "SYN-A"), ("SYN-B", "SYN-B")], required=False)
    units = forms.IntegerField(min_value=1, max_value=100, required=False)
    unit_amount = forms.DecimalField(min_value=0, max_value=9999.99, decimal_places=2, required=False)
    currency = forms.ChoiceField(choices=[("USD", "USD")], required=False)
    reason = forms.CharField(max_length=500)

    def __init__(self, *args, decision_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["identity_decision_id"].choices = decision_choices


class ClaimPrepareForm(RequestForm):
    expected_claim_revision_id = forms.UUIDField(required=False, widget=forms.HiddenInput)
    selected_service_revision_ids = forms.MultipleChoiceField(
        widget=forms.CheckboxSelectMultiple, label="Exact current service revisions"
    )
    route = forms.ChoiceField(choices=[
        ("synthetic-receiver/v1", "synthetic-receiver/v1"),
        ("synthetic-receiver/v2", "synthetic-receiver/v2"),
    ])
    reason = forms.CharField(max_length=500)

    def __init__(self, *args, service_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["selected_service_revision_ids"].choices = service_choices


class ApprovalForm(RequestForm):
    claim_revision_id = forms.UUIDField(widget=forms.HiddenInput)
    expected_envelope_digest = forms.CharField(widget=forms.HiddenInput, max_length=64)


class PolicySelectionForm(RequestForm):
    expected_version = forms.CharField(widget=forms.HiddenInput)
    expected_generation = forms.IntegerField(widget=forms.HiddenInput)
    version = forms.ChoiceField(choices=[
        ("synthetic-v1", "synthetic-v1: SYN-A and SYN-B"),
        ("synthetic-v2", "synthetic-v2: SYN-A only"),
    ])


class DeliveryRequestForm(RequestForm):
    claim_revision_id = forms.UUIDField(widget=forms.HiddenInput)
    expected_envelope_digest = forms.CharField(widget=forms.HiddenInput, max_length=64)


class DeliveryCancelForm(RequestForm):
    intent_id = forms.UUIDField(widget=forms.HiddenInput)


class DeliveryRetryForm(RequestForm):
    intent_id = forms.UUIDField(widget=forms.HiddenInput)
    expected_attempt_id = forms.UUIDField(widget=forms.HiddenInput)


class DeliveryReconcileForm(forms.Form):
    intent_id = forms.UUIDField(widget=forms.HiddenInput)
