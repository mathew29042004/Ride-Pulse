from django.urls import path, re_path

from . import views

app_name = "portal"

# Everything that isn't the API, admin, static/media files or a WebSocket goes to the SPA.
urlpatterns = [
    path("sw.js", views.service_worker, name="service-worker"),
    re_path(r"^(?!api/|admin/|static/|media/|ws/|metrics$).*$", views.spa, name="spa"),
]
