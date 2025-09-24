"""
Custom error handlers for SurveyEarn Platform
"""
from django.shortcuts import render
from django.http import HttpResponseBadRequest, HttpResponseForbidden, HttpResponseNotFound
from django.views.decorators.csrf import requires_csrf_token
import logging

logger = logging.getLogger(__name__)

def handler400(request, exception=None):
    """Custom 400 Bad Request error handler"""
    logger.warning(f"400 Bad Request: {request.path} from {request.META.get('REMOTE_ADDR')}")
    return HttpResponseBadRequest(render(request, 'errors/400.html').content)

def handler401(request, exception=None):
    """Custom 401 Unauthorized error handler"""
    logger.warning(f"401 Unauthorized: {request.path} from {request.META.get('REMOTE_ADDR')}")
    return render(request, 'errors/401.html', status=401)

def handler403(request, exception=None):
    """Custom 403 Forbidden error handler"""
    logger.warning(f"403 Forbidden: {request.path} from {request.META.get('REMOTE_ADDR')}")
    return HttpResponseForbidden(render(request, 'errors/403.html').content)

def handler404(request, exception=None):
    """Custom 404 Not Found error handler"""
    logger.info(f"404 Not Found: {request.path} from {request.META.get('REMOTE_ADDR')}")
    return HttpResponseNotFound(render(request, 'errors/404.html').content)

def handler405(request, exception=None):
    """Custom 405 Method Not Allowed error handler"""
    logger.warning(f"405 Method Not Allowed: {request.method} {request.path} from {request.META.get('REMOTE_ADDR')}")
    return render(request, 'errors/405.html', status=405)

def handler408(request, exception=None):
    """Custom 408 Request Timeout error handler"""
    logger.warning(f"408 Request Timeout: {request.path} from {request.META.get('REMOTE_ADDR')}")
    return render(request, 'errors/408.html', status=408)

def handler410(request, exception=None):
    """Custom 410 Gone error handler"""
    logger.info(f"410 Gone: {request.path} from {request.META.get('REMOTE_ADDR')}")
    return render(request, 'errors/410.html', status=410)

def handler413(request, exception=None):
    """Custom 413 Payload Too Large error handler"""
    logger.warning(f"413 Payload Too Large: {request.path} from {request.META.get('REMOTE_ADDR')}")
    return render(request, 'errors/413.html', status=413)

def handler422(request, exception=None):
    """Custom 422 Unprocessable Entity error handler"""
    logger.warning(f"422 Unprocessable Entity: {request.path} from {request.META.get('REMOTE_ADDR')}")
    return render(request, 'errors/422.html', status=422)

def handler429(request, exception=None):
    """Custom 429 Too Many Requests error handler"""
    logger.warning(f"429 Too Many Requests: {request.path} from {request.META.get('REMOTE_ADDR')}")
    return render(request, 'errors/429.html', status=429)

@requires_csrf_token
def handler500(request):
    """Custom 500 Internal Server Error handler"""
    logger.error(f"500 Internal Server Error: {request.path} from {request.META.get('REMOTE_ADDR')}")
    return render(request, 'errors/500.html', status=500)

def handler502(request, exception=None):
    """Custom 502 Bad Gateway error handler"""
    logger.error(f"502 Bad Gateway: {request.path} from {request.META.get('REMOTE_ADDR')}")
    return render(request, 'errors/502.html', status=502)

def handler503(request, exception=None):
    """Custom 503 Service Unavailable error handler"""
    logger.warning(f"503 Service Unavailable: {request.path} from {request.META.get('REMOTE_ADDR')}")
    return render(request, 'errors/503.html', status=503)

def handler504(request, exception=None):
    """Custom 504 Gateway Timeout error handler"""
    logger.warning(f"504 Gateway Timeout: {request.path} from {request.META.get('REMOTE_ADDR')}")
    return render(request, 'errors/504.html', status=504)