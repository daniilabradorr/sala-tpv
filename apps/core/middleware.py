"""HTTP adaptations shared by progressively enhanced views."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import resolve_url


class HtmxLoginRedirectMiddleware:
    """Turn only authentication redirects into full HTMX navigations."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not getattr(request, "htmx", False) or response.status_code not in {
            301,
            302,
            303,
            307,
            308,
        }:
            return response
        location = response.get("Location", "")
        if urlsplit(location).path != urlsplit(resolve_url(settings.LOGIN_URL)).path:
            return response
        if request.headers.get("X-Netxodo-Authenticated-Shell") == "1":
            parts = urlsplit(location)
            query = dict(parse_qsl(parts.query, keep_blank_values=True))
            query["expired"] = "1"
            location = urlunsplit(
                (
                    parts.scheme,
                    parts.netloc,
                    parts.path,
                    urlencode(query),
                    parts.fragment,
                )
            )
        htmx_response = HttpResponse(status=204)
        htmx_response["HX-Redirect"] = location
        return htmx_response
