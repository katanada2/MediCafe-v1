from django.urls import path

from . import views


urlpatterns = [
    path("", views.home, name="home"),
    path("org/<uuid:organization_id>/", views.worklist, name="worklist"),
    path("org/<uuid:organization_id>/upload/", views.upload, name="upload"),
    path("org/<uuid:organization_id>/delivery/<uuid:delivery_id>/", views.delivery_detail, name="delivery_detail"),
    path("org/<uuid:organization_id>/delivery/<uuid:delivery_id>/parse/", views.parse_view, name="parse_delivery"),
    path("org/<uuid:organization_id>/observation/<uuid:observation_id>/", views.observation_detail, name="observation_detail"),
]

