from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponseNotAllowed
from django.shortcuts import redirect, render

from medicafe_v1.access.services import AuthorizationError
from medicafe_v1.sources.artifacts import LocalArtifactStore
from medicafe_v1.sources.domain import CommandError
from medicafe_v1.sources.queries import outcome_deliveries

from .commands import accept_lifecycle, interpret_inbound, post_remittance, reevaluate_candidate
from .forms import CandidateCommandForm, InterpretForm, ReevaluateForm
from .models import AcceptedEventEvidence, InboundCandidate
from .queries import candidate_detail, inbound_candidates, ledger_detail


def _inbox_context(request, organization_id, *, interpret_form=None):
    return {
        "organization_id": organization_id,
        "deliveries": outcome_deliveries(
            actor=request.user, organization_id=organization_id,
        ),
        "candidates": inbound_candidates(
            actor=request.user, organization_id=organization_id,
        ),
        "interpret_form": interpret_form,
    }


@login_required
def outcomes_inbox(request, organization_id):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    try:
        context = _inbox_context(request, organization_id)
    except AuthorizationError as exc:
        raise Http404 from exc
    return render(request, "outcomes/inbox.html", context)


@login_required
def interpret_delivery(request, organization_id, delivery_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    form = InterpretForm(request.POST)
    try:
        if form.is_valid():
            if form.cleaned_data["target_id"] != delivery_id:
                form.add_error("target_id", "delivery_not_for_page")
            else:
                result = interpret_inbound(
                    actor=request.user, organization_id=organization_id,
                    delivery_id=delivery_id, artifact_store=LocalArtifactStore(),
                )
                messages.success(request, result.reason_code)
                return redirect(
                    "outcomes_candidate_detail", organization_id=organization_id,
                    candidate_id=result.candidate_id,
                )
        context = _inbox_context(request, organization_id, interpret_form=form)
    except AuthorizationError as exc:
        raise Http404 from exc
    except CommandError as exc:
        form.add_error(None, exc.reason_code)
        context = _inbox_context(request, organization_id, interpret_form=form)
    return render(request, "outcomes/inbox.html", context)


def _candidate_context(request, organization_id, candidate_id, *, active_form=None):
    candidate = candidate_detail(
        actor=request.user, organization_id=organization_id, candidate_id=candidate_id,
    )
    result = reevaluate_candidate(
        actor=request.user, organization_id=organization_id,
        candidate_id=candidate.id, artifact_store=LocalArtifactStore(),
    )
    evidence = AcceptedEventEvidence.objects.filter(
        organization_id=organization_id, candidate=candidate,
    ).select_related("event").first()
    ledger = None
    if evidence and evidence.event.kind == InboundCandidate.KIND_REMITTANCE:
        ledger = ledger_detail(
            actor=request.user, organization_id=organization_id,
            claim_revision_id=evidence.event.claim_revision_id,
        )
    forms = {
        "accept_form": CandidateCommandForm(
            initial={"target_id": candidate.id}, prefix="accept",
        ),
        "post_form": CandidateCommandForm(
            initial={"target_id": candidate.id}, prefix="post",
        ),
        "reevaluate_form": ReevaluateForm(
            initial={"target_id": candidate.id}, prefix="reevaluate",
        ),
    }
    if active_form is not None:
        forms[active_form[0]] = active_form[1]
    return {
        "organization_id": organization_id, "candidate": candidate,
        "blockers": result.current_blockers, "evidence": evidence,
        "ledger": ledger, **forms,
    }


@login_required
def candidate_review(request, organization_id, candidate_id):
    if request.method not in {"GET", "POST"}:
        return HttpResponseNotAllowed(["GET", "POST"])
    active = None
    try:
        if request.method == "POST":
            action = request.POST.get("action")
            if action in {"accept", "post"}:
                key = "accept_form" if action == "accept" else "post_form"
                prefix = "accept" if action == "accept" else "post"
                form = CandidateCommandForm(request.POST, prefix=prefix)
            elif action == "reevaluate":
                key = "reevaluate_form"
                form = ReevaluateForm(request.POST, prefix="reevaluate")
            else:
                return HttpResponseNotAllowed(["GET", "POST"])
            active = (key, form)
            if form.is_valid():
                if form.cleaned_data["target_id"] != candidate_id:
                    form.add_error("target_id", "candidate_not_for_page")
                elif action == "accept":
                    result = accept_lifecycle(
                        actor=request.user, organization_id=organization_id,
                        request_id=form.cleaned_data["request_uuid"],
                        candidate_id=candidate_id, artifact_store=LocalArtifactStore(),
                    )
                    messages.success(request, result.reason_code)
                    return redirect("outcomes_candidate_detail", organization_id=organization_id,
                                    candidate_id=candidate_id)
                elif action == "post":
                    result = post_remittance(
                        actor=request.user, organization_id=organization_id,
                        request_id=form.cleaned_data["request_uuid"],
                        candidate_id=candidate_id, artifact_store=LocalArtifactStore(),
                    )
                    messages.success(request, result.reason_code)
                    return redirect("outcomes_candidate_detail", organization_id=organization_id,
                                    candidate_id=candidate_id)
                else:
                    result = reevaluate_candidate(
                        actor=request.user, organization_id=organization_id,
                        candidate_id=candidate_id, artifact_store=LocalArtifactStore(),
                    )
                    messages.info(request, result.reason_code)
                    return redirect("outcomes_candidate_detail", organization_id=organization_id,
                                    candidate_id=candidate_id)
        context = _candidate_context(
            request, organization_id, candidate_id, active_form=active,
        )
    except AuthorizationError as exc:
        raise Http404 from exc
    except CommandError as exc:
        if active is None:
            raise Http404 from exc
        active[1].add_error(None, exc.reason_code)
        context = _candidate_context(
            request, organization_id, candidate_id, active_form=active,
        )
    return render(request, "outcomes/candidate_detail.html", context)
