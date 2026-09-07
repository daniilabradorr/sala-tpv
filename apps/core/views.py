from django.http import JsonResponse
from django.shortcuts import render


def health_check(request):
    return JsonResponse({"status": "ok"}, status=200)


def csrf_failure(request, reason=""):
    """Render the generic forbidden page without exposing CSRF details."""

    return render(request, "403.html", status=403)
