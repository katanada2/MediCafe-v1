from django.urls import path

from . import views


urlpatterns = [
    path("org/<uuid:organization_id>/outcomes/", views.outcomes_inbox,
         name="outcomes_inbox"),
    path("org/<uuid:organization_id>/outcomes/delivery/<uuid:delivery_id>/interpret/",
         views.interpret_delivery, name="outcomes_interpret"),
    path("org/<uuid:organization_id>/outcomes/candidate/<uuid:candidate_id>/",
         views.candidate_review, name="outcomes_candidate_detail"),
]
