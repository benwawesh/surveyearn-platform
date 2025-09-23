from django.shortcuts import redirect


class AdminRedirectMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Check if user is admin and trying to access user URLs
        if (request.user.is_authenticated and
                request.user.is_staff and
                request.path.startswith('/accounts/')):
            # Redirect admin users back to admin dashboard
            return redirect('custom_admin:dashboard')

        response = self.get_response(request)
        return response