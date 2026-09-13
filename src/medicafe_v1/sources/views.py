from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponseNotAllowed
from django.shortcuts import redirect, render

from medicafe_v1.access.models import Membership
from medicafe_v1.access.services import AuthorizationError
from medicafe_v1.records.commands import ResolutionIntent, resolve_identity
from medicafe_v1.records.models import Encounter, IdentityDecision
from medicafe_v1.records.queries import exact_alias_suggestion

from .commands import admit_delivery, parse_delivery
from .domain import CommandError
from .forms import ResolutionForm, UploadForm
from .models import Delivery, Observation, ParseAttempt, ParseResult
from .parsers import PARSER_VERSION
from .queries import scoped_deliveries, scoped_observations


def _deny_on_authorization(callable_):
    try:
        return callable_()
    except AuthorizationError as exc:
        raise Http404 from exc


@login_required
def home(request):
    membership = Membership.objects.filter(user=request.user, is_active=True).first()
    if not membership:
        raise Http404
    return redirect("worklist", organization_id=membership.organization_id)


@login_required
def worklist(request, organization_id):
    deliveries = list(_deny_on_authorization(lambda: scoped_deliveries(
        actor=request.user, organization_id=organization_id
    )))
    for delivery in deliveries:
        delivery.requested_result = ParseResult.objects.filter(
            organization_id=organization_id, delivery=delivery, parser_version=PARSER_VERSION
        ).first()
        delivery.latest_requested_attempt = ParseAttempt.objects.filter(
            organization_id=organization_id, delivery=delivery, parser_version=PARSER_VERSION
        ).order_by("-ended_at").first()
    unresolved = _deny_on_authorization(lambda: scoped_observations(
        actor=request.user, organization_id=organization_id, unresolved_only=True
    ))
    return render(request, "sources/worklist.html", {
        "organization_id": organization_id, "deliveries": deliveries, "unresolved": unresolved,
    })


@login_required
def upload(request, organization_id):
    if request.method not in {"GET", "POST"}:
        return HttpResponseNotAllowed(["GET", "POST"])
    form = UploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        source_file = form.cleaned_data["source_file"]
        try:
            result = admit_delivery(
                actor=request.user, organization_id=organization_id,
                source_namespace=form.cleaned_data["source_namespace"],
                source_key=str(form.cleaned_data["source_key"]), content=source_file.read(),
                media_type=source_file.content_type,
                supersedes_id=form.cleaned_data.get("supersedes_id"),
            )
        except (CommandError, AuthorizationError) as exc:
            form.add_error(None, exc.reason_code)
        else:
            messages.success(request, result.reason_code)
            return redirect("delivery_detail", organization_id=organization_id, delivery_id=result.delivery_id)
    return render(request, "sources/upload.html", {"form": form, "organization_id": organization_id})


@login_required
def delivery_detail(request, organization_id, delivery_id):
    deliveries = _deny_on_authorization(lambda: scoped_deliveries(
        actor=request.user, organization_id=organization_id
    ))
    try:
        delivery = next(item for item in deliveries if item.id == delivery_id)
    except StopIteration as exc:
        raise Http404 from exc
    observations = _deny_on_authorization(lambda: scoped_observations(
        actor=request.user, organization_id=organization_id, delivery_id=delivery_id
    ))
    results = ParseResult.objects.filter(organization_id=organization_id, delivery=delivery)
    attempts = ParseAttempt.objects.filter(organization_id=organization_id, delivery=delivery).order_by("-ended_at")
    return render(request, "sources/delivery_detail.html", {
        "organization_id": organization_id, "delivery": delivery, "observations": observations,
        "results": results, "attempts": attempts,
    })


@login_required
def parse_view(request, organization_id, delivery_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        result = parse_delivery(actor=request.user, organization_id=organization_id, delivery_id=delivery_id)
    except (CommandError, AuthorizationError) as exc:
        messages.error(request, exc.reason_code)
    else:
        messages.success(request, result.reason_code)
    return redirect("delivery_detail", organization_id=organization_id, delivery_id=delivery_id)


@login_required
def observation_detail(request, organization_id, observation_id):
    observations = _deny_on_authorization(lambda: scoped_observations(
        actor=request.user, organization_id=organization_id
    ))
    try:
        observation = observations.get(id=observation_id)
    except Observation.DoesNotExist as exc:
        raise Http404 from exc
    decision = IdentityDecision.objects.filter(organization_id=organization_id, observation=observation).first()
    encounters = Encounter.objects.filter(organization_id=organization_id).select_related("patient")
    patient_ref = observation.normalized_values.get("patient_ref")
    suggestion = None
    if patient_ref:
        suggestion = _deny_on_authorization(lambda: exact_alias_suggestion(
            actor=request.user, organization_id=organization_id,
            namespace="synthetic-patient-ref", value=patient_ref,
        ))
    initial = {
        "alias_value": observation.normalized_values.get("patient_ref"),
        "service_date": observation.normalized_values.get("service_date"),
        "display_name": "Synthetic patient",
    }
    form = ResolutionForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        cleaned = form.cleaned_data
        intent = ResolutionIntent(
            mode=cleaned["mode"], reason=cleaned["reason"],
            patient_id=str(cleaned["patient_id"]) if cleaned.get("patient_id") else None,
            encounter_id=str(cleaned["encounter_id"]) if cleaned.get("encounter_id") else None,
            display_name=cleaned.get("display_name"), alias_namespace=cleaned.get("alias_namespace"),
            alias_value=cleaned.get("alias_value"),
            service_date=cleaned["service_date"].isoformat() if cleaned.get("service_date") else None,
        )
        try:
            result = resolve_identity(
                actor=request.user, organization_id=organization_id, observation_id=observation_id,
                request_uuid=cleaned["request_uuid"], intent=intent,
            )
        except (CommandError, AuthorizationError) as exc:
            form.add_error(None, exc.reason_code)
        else:
            messages.success(request, result.reason_code)
            return redirect("observation_detail", organization_id=organization_id, observation_id=observation_id)
    return render(request, "sources/observation_detail.html", {
        "organization_id": organization_id, "observation": observation,
        "decision": decision, "encounters": encounters, "suggestion": suggestion, "form": form,
    })
