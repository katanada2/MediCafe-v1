from django.urls import path

from . import views


urlpatterns = [
    path("org/<uuid:organization_id>/archive/encounter/<uuid:encounter_id>/",
         views.archive_encounter, name="archive_encounter"),
    path("org/<uuid:organization_id>/archive/projection/<uuid:projection_id>/",
         views.archive_projection, name="archive_projection_detail"),
    path("org/<uuid:organization_id>/archive/batch/<uuid:batch_id>/",
         views.archive_batch, name="archive_batch_detail"),
]
