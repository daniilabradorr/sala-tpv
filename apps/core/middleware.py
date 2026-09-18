"""HTTP adaptations shared by progressively enhanced views."""

from urllib.parse import urlsplit

from django.conf import settings
from django.http import HttpResponse
from django.urls import resolve_url


class HtmxLoginRedirectMiddleware:
    """Turn only authentication redirects into full HTMX navigations."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not request.htmx or response.status_code not in {301, 302, 303, 307, 308}:
            return response
        location = response.get("Location", "")
        if urlsplit(location).path != urlsplit(resolve_url(settings.LOGIN_URL)).path:
            return response
        htmx_response = HttpResponse(status=204)
        htmx_response["HX-Redirect"] = location
        return htmx_response
