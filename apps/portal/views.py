"""Serves the React single-page app; client-side routing takes over from there."""

from django.conf import settings
from django.http import Http404, HttpResponse
from django.views.decorators.cache import never_cache

INDEX = settings.BASE_DIR / "frontend" / "dist" / "index.html"
SERVICE_WORKER = settings.BASE_DIR / "frontend" / "public" / "sw.js"

NOT_BUILT = """<!doctype html><meta charset="utf-8"><title>Ride Pulse</title>
<body style="font-family:system-ui;max-width:640px;margin:80px auto;padding:0 20px;line-height:1.6">
<h1>Ride Pulse API is running</h1>
<p>The React front end hasn't been built yet. Run <code>make frontend</code> (or
<code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code>) and reload, or use the
Vite dev server on <a href="http://localhost:5173">localhost:5173</a>.</p>
<p><a href="/api/docs/">API docs</a> · <a href="/admin/">Django admin</a></p></body>"""


@never_cache
def spa(request, *args, **kwargs):
    if INDEX.exists():
        return HttpResponse(INDEX.read_bytes(), content_type="text/html; charset=utf-8")
    return HttpResponse(NOT_BUILT, status=200)


@never_cache
def service_worker(request):
    """The PWA service worker. Served from the site root (not /static/) so it can control
    every page of the app; never cached, so updates roll out on the next visit."""
    if not SERVICE_WORKER.exists():
        raise Http404
    response = HttpResponse(SERVICE_WORKER.read_bytes(), content_type="text/javascript")
    response["Service-Worker-Allowed"] = "/"
    return response
