from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponseNotAllowed
from django.shortcuts import redirect, render

from medicafe_v1.access.services import AuthorizationError, require_active_membership
from medicafe_v1.records.commands import accept_service, revise_service
from medicafe_v1.records.models import IdentityDecision
from medicafe_v1.records.queries import current_services_for_encounter, service_detail
from medicafe_v1.sources.domain import CommandError

from .commands import approve_claim_revision, prepare_claim_revision, select_synthetic_policy
from .forms import (
    ApprovalForm, ClaimPrepareForm, PolicySelectionForm, ServiceAcceptForm,
    ServiceRevisionForm,
)
from .models import SyntheticPolicySelection
from .queries import claim_actionability, claim_detail, claim_for_encounter


def _decisions(actor, organization_id, encounter_id):
    # Admission is established by the records-owned active-membership query first.
    list(current_services_for_encounter(
        actor=actor, organization_id=organization_id, encounter_id=encounter_id
    ))
    return IdentityDecision.objects.filter(
        organization_id=organization_id, encounter_id=encounter_id
    ).select_related("observation").order_by("decided_at")


def _decision_choices(decisions):
    return [(str(item.id), f"row {item.observation.row_ordinal}: {item.reason}") for item in decisions]


@login_required
def encounter_services(request, organization_id, encounter_id):
    if request.method not in {"GET", "POST"}:
        return HttpResponseNotAllowed(["GET", "POST"])
    try:
        services = list(current_services_for_encounter(
            actor=request.user, organization_id=organization_id, encounter_id=encounter_id
        ))
        decisions = list(_decisions(request.user, organization_id, encounter_id))
    except AuthorizationError as exc:
        raise Http404 from exc
    choices = _decision_choices(decisions)
    form = ServiceAcceptForm(request.POST or None, decision_choices=choices,
                             initial={"currency": "USD", "units": 1})
    if request.method == "POST" and form.is_valid():
        decision = next((item for item in decisions if str(item.id) == form.cleaned_data["identity_decision_id"]), None)
        if not decision:
            form.add_error("identity_decision_id", "service_evidence_not_resolved")
        else:
            try:
                result = accept_service(
                    actor=request.user, organization_id=organization_id,
                    request_id=form.cleaned_data["request_uuid"], identity_decision_id=decision.id,
                    evidence_observation_id=decision.observation_id, code=form.cleaned_data["code"],
                    units=form.cleaned_data["units"], unit_amount=form.cleaned_data["unit_amount"],
                    currency=form.cleaned_data["currency"], reason=form.cleaned_data["reason"],
                )
            except (CommandError, AuthorizationError) as exc:
                form.add_error(None, exc.reason_code)
            else:
                messages.success(request, result.reason_code)
                return redirect("service_detail", organization_id=organization_id, service_id=result.service_id)
    claim = claim_for_encounter(
        actor=request.user, organization_id=organization_id, encounter_id=encounter_id
    )
    return render(request, "claims/encounter_services.html", {
        "organization_id": organization_id, "encounter_id": encounter_id,
        "services": services, "form": form, "claim": claim,
    })


@login_required
def service_review(request, organization_id, service_id):
    if request.method not in {"GET", "POST"}:
        return HttpResponseNotAllowed(["GET", "POST"])
    try:
        service = service_detail(actor=request.user, organization_id=organization_id, service_id=service_id)
        decisions = list(_decisions(request.user, organization_id, service.encounter_id))
    except (AuthorizationError, CommandError) as exc:
        raise Http404 from exc
    current = service.current_revision
    form = ServiceRevisionForm(
        request.POST or None, decision_choices=_decision_choices(decisions), initial={
            "expected_revision_id": current.id, "disposition": current.disposition,
            "code": current.code, "units": current.units, "unit_amount": current.unit_amount,
            "currency": current.currency,
        },
    )
    if request.method == "POST" and form.is_valid():
        decision = next((item for item in decisions if str(item.id) == form.cleaned_data["identity_decision_id"]), None)
        if not decision:
            form.add_error("identity_decision_id", "service_evidence_not_resolved")
        else:
            try:
                result = revise_service(
                    actor=request.user, organization_id=organization_id,
                    request_id=form.cleaned_data["request_uuid"], service_id=service.id,
                    expected_revision_id=form.cleaned_data["expected_revision_id"],
                    evidence_observation_id=decision.observation_id,
                    disposition=form.cleaned_data["disposition"], code=form.cleaned_data.get("code"),
                    units=form.cleaned_data.get("units"), unit_amount=form.cleaned_data.get("unit_amount"),
                    currency=form.cleaned_data.get("currency"), reason=form.cleaned_data["reason"],
                )
            except (CommandError, AuthorizationError) as exc:
                form.add_error(None, exc.reason_code)
            else:
                messages.success(request, result.reason_code)
                return redirect("service_detail", organization_id=organization_id, service_id=service.id)
    return render(request, "claims/service_detail.html", {
        "organization_id": organization_id, "service": service,
        "revisions": service.revisions.order_by("revision_number"), "form": form,
    })


@login_required
def prepare_claim(request, organization_id, encounter_id):
    if request.method not in {"GET", "POST"}:
        return HttpResponseNotAllowed(["GET", "POST"])
    try:
        services = list(current_services_for_encounter(
            actor=request.user, organization_id=organization_id, encounter_id=encounter_id
        ))
        claim = claim_for_encounter(
            actor=request.user, organization_id=organization_id, encounter_id=encounter_id
        )
    except AuthorizationError as exc:
        raise Http404 from exc
    accepted = [item for item in services if item.current_revision.disposition == "accepted"]
    choices = [
        (str(item.current_revision_id),
         f"{item.current_revision.code} x {item.current_revision.units} @ {item.current_revision.unit_amount:.2f}")
        for item in accepted
    ]
    form = ClaimPrepareForm(
        request.POST or None, service_choices=choices,
        initial={"expected_claim_revision_id": claim.current_revision_id if claim else None},
    )
    if request.method == "POST" and form.is_valid():
        route_id, route_version = form.cleaned_data["route"].split("/", 1)
        try:
            result = prepare_claim_revision(
                actor=request.user, organization_id=organization_id,
                request_id=form.cleaned_data["request_uuid"], encounter_id=encounter_id,
                expected_claim_revision_id=form.cleaned_data.get("expected_claim_revision_id"),
                selected_service_revision_ids=form.cleaned_data["selected_service_revision_ids"],
                route_id=route_id, route_version=route_version, reason=form.cleaned_data["reason"],
            )
        except (CommandError, AuthorizationError) as exc:
            form.add_error(None, exc.reason_code)
        else:
            messages.success(request, result.reason_code)
            return redirect("claim_detail", organization_id=organization_id, claim_id=result.claim_id)
    return render(request, "claims/prepare_claim.html", {
        "organization_id": organization_id, "encounter_id": encounter_id,
        "services": services, "form": form, "claim": claim,
    })


@login_required
def claim_review(request, organization_id, claim_id):
    if request.method not in {"GET", "POST"}:
        return HttpResponseNotAllowed(["GET", "POST"])
    try:
        claim = claim_detail(actor=request.user, organization_id=organization_id, claim_id=claim_id)
    except (AuthorizationError, CommandError) as exc:
        raise Http404 from exc
    current = claim.current_revision
    form = ApprovalForm(request.POST or None, initial={
        "claim_revision_id": current.id, "expected_envelope_digest": current.envelope_digest,
    })
    if request.method == "POST" and form.is_valid():
        try:
            result = approve_claim_revision(
                actor=request.user, organization_id=organization_id,
                request_id=form.cleaned_data["request_uuid"],
                claim_revision_id=form.cleaned_data["claim_revision_id"],
                expected_envelope_digest=form.cleaned_data["expected_envelope_digest"],
            )
        except (CommandError, AuthorizationError) as exc:
            form.add_error(None, exc.reason_code)
        else:
            messages.success(request, result.reason_code)
            return redirect("claim_detail", organization_id=organization_id, claim_id=claim.id)
    actionability = claim_actionability(
        actor=request.user, organization_id=organization_id, claim_revision_id=current.id
    )
    return render(request, "claims/claim_detail.html", {
        "organization_id": organization_id, "claim": claim, "revision": current,
        "lines": current.lines.order_by("ordinal"), "form": form,
        "actionability": actionability,
    })


@login_required
def policy_settings(request, organization_id):
    if request.method not in {"GET", "POST"}:
        return HttpResponseNotAllowed(["GET", "POST"])
    try:
        require_active_membership(actor=request.user, organization_id=organization_id)
    except AuthorizationError as exc:
        raise Http404 from exc
    selection = SyntheticPolicySelection.objects.filter(organization_id=organization_id).first()
    if not selection:
        raise Http404
    form = PolicySelectionForm(request.POST or None, initial={
        "expected_version": selection.version,
        "expected_generation": selection.activation_generation,
        "version": selection.version,
    })
    if request.method == "POST" and form.is_valid():
        try:
            result = select_synthetic_policy(
                actor=request.user, organization_id=organization_id,
                request_id=form.cleaned_data["request_uuid"],
                expected_version=form.cleaned_data["expected_version"],
                expected_generation=form.cleaned_data["expected_generation"],
                version=form.cleaned_data["version"],
            )
        except (CommandError, AuthorizationError) as exc:
            form.add_error(None, exc.reason_code)
        else:
            messages.success(request, result.reason_code)
            return redirect("policy_settings", organization_id=organization_id)
    return render(request, "claims/policy_settings.html", {
        "organization_id": organization_id, "selection": selection, "form": form,
    })
