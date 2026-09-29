from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponseNotAllowed
from django.shortcuts import redirect, render

from medicafe_v1.access.services import AuthorizationError
from medicafe_v1.sources.domain import CommandError

from .commands import capture_archive_projection, queue_archive_batch, retry_archive_item
from .forms import CaptureForm, QueueForm, ReconcileForm, RetryForm
from .queries import (
    archive_batch_detail, archive_batch_status, archive_current_lag,
    archive_item_status, archive_projection_detail,
)
from .worker import reconcile_archive_item


@login_required
def archive_encounter(request, organization_id, encounter_id):
    if request.method not in {"GET", "POST"}:
        return HttpResponseNotAllowed(["GET", "POST"])
    try:
        lag = archive_current_lag(
            actor=request.user, organization_id=organization_id,
            encounter_id=encounter_id,
        )
    except AuthorizationError as exc:
        raise Http404 from exc
    except CommandError as exc:
        raise Http404 from exc
    form = CaptureForm(request.POST or None, initial={
        "target_id": encounter_id,
        "expected_projection_id": lag.head_projection_id,
    })
    if request.method == "POST" and form.is_valid():
        if form.cleaned_data["target_id"] != encounter_id:
            form.add_error("target_id", "encounter_not_for_page")
        else:
            try:
                result = capture_archive_projection(
                    actor=request.user, organization_id=organization_id,
                    request_id=form.cleaned_data["request_uuid"],
                    encounter_id=encounter_id,
                    expected_projection_id=form.cleaned_data.get("expected_projection_id"),
                )
            except (CommandError, AuthorizationError) as exc:
                form.add_error(None, exc.reason_code)
            else:
                messages.success(request, result.reason_code)
                return redirect(
                    "archive_projection_detail", organization_id=organization_id,
                    projection_id=result.projection_id,
                )
    return render(request, "archival/encounter.html", {
        "organization_id": organization_id, "encounter_id": encounter_id,
        "lag": lag, "form": form,
    })


def _projection_context(request, organization_id, projection_id, *, active=None):
    projection = archive_projection_detail(
        actor=request.user, organization_id=organization_id,
        projection_id=projection_id,
    )
    status = archive_item_status(
        actor=request.user, organization_id=organization_id,
        projection_id=projection.id,
    )
    latest = projection.attempts.order_by("-started_at", "id").first()
    forms = {
        "queue_form": QueueForm(initial={"target_id": projection.id}, prefix="queue"),
        "retry_form": RetryForm(initial={
            "target_id": projection.id,
            "expected_attempt_id": latest.id if latest else None,
        }, prefix="retry"),
        "reconcile_form": ReconcileForm(
            initial={"target_id": projection.id}, prefix="reconcile",
        ),
    }
    if active:
        forms[active[0]] = active[1]
    return {
        "organization_id": organization_id, "projection": projection,
        "status": status, "latest": latest, **forms,
    }


@login_required
def archive_projection(request, organization_id, projection_id):
    if request.method not in {"GET", "POST"}:
        return HttpResponseNotAllowed(["GET", "POST"])
    active = None
    try:
        if request.method == "POST":
            action = request.POST.get("action")
            if action == "queue":
                active = ("queue_form", QueueForm(request.POST, prefix="queue"))
            elif action == "retry":
                active = ("retry_form", RetryForm(request.POST, prefix="retry"))
            elif action == "reconcile":
                active = ("reconcile_form", ReconcileForm(request.POST, prefix="reconcile"))
            else:
                return HttpResponseNotAllowed(["GET", "POST"])
            form = active[1]
            if form.is_valid():
                if form.cleaned_data["target_id"] != projection_id:
                    form.add_error("target_id", "archive_projection_not_for_page")
                elif action == "queue":
                    result = queue_archive_batch(
                        actor=request.user, organization_id=organization_id,
                        request_id=form.cleaned_data["request_uuid"],
                        projection_ids=[projection_id],
                    )
                    messages.success(request, result.reason_code)
                    return redirect("archive_batch_detail", organization_id=organization_id,
                                    batch_id=result.batch_id)
                elif action == "retry":
                    result = retry_archive_item(
                        actor=request.user, organization_id=organization_id,
                        request_id=form.cleaned_data["request_uuid"],
                        projection_id=projection_id,
                        expected_attempt_id=form.cleaned_data["expected_attempt_id"],
                    )
                    messages.success(request, result.reason_code)
                    return redirect("archive_projection_detail", organization_id=organization_id,
                                    projection_id=projection_id)
                else:
                    result = reconcile_archive_item(
                        actor=request.user, organization_id=organization_id,
                        projection_id=projection_id,
                    )
                    messages.info(request, result.reason_code)
                    return redirect("archive_projection_detail", organization_id=organization_id,
                                    projection_id=projection_id)
        context = _projection_context(
            request, organization_id, projection_id, active=active,
        )
    except AuthorizationError as exc:
        raise Http404 from exc
    except CommandError as exc:
        if active is None:
            raise Http404 from exc
        active[1].add_error(None, exc.reason_code)
        context = _projection_context(
            request, organization_id, projection_id, active=active,
        )
    return render(request, "archival/projection.html", context)


@login_required
def archive_batch(request, organization_id, batch_id):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    try:
        batch = archive_batch_detail(
            actor=request.user, organization_id=organization_id, batch_id=batch_id,
        )
        statuses = archive_batch_status(
            actor=request.user, organization_id=organization_id, batch_id=batch_id,
        )
    except AuthorizationError as exc:
        raise Http404 from exc
    except CommandError as exc:
        raise Http404 from exc
    return render(request, "archival/batch.html", {
        "organization_id": organization_id, "batch": batch,
        "rows": zip(batch.items.order_by("ordinal"), statuses),
    })
