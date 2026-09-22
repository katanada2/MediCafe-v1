from django.urls import path

from . import views


urlpatterns = [
    path("org/<uuid:organization_id>/encounter/<uuid:encounter_id>/services/",
         views.encounter_services, name="encounter_services"),
    path("org/<uuid:organization_id>/service/<uuid:service_id>/",
         views.service_review, name="service_detail"),
    path("org/<uuid:organization_id>/encounter/<uuid:encounter_id>/claim/prepare/",
         views.prepare_claim, name="prepare_claim"),
    path("org/<uuid:organization_id>/claim/<uuid:claim_id>/",
         views.claim_review, name="claim_detail"),
    path("org/<uuid:organization_id>/synthetic-policy/",
         views.policy_settings, name="policy_settings"),
]
