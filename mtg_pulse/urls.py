from django.contrib import admin
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.urls import include, path, reverse_lazy


class PasswordChangeView(auth_views.PasswordChangeView):
    # Named explicitly: the admin's registration/password_change_form.html would win otherwise.
    template_name = 'theme/password_change.html'
    success_url = reverse_lazy('profile')

    def form_valid(self, form):
        messages.success(self.request, 'Password changed.', extra_tags='account')
        return super().form_valid(form)


urlpatterns = [
    path('admin/', admin.site.urls),
    # Accounts are created by the administrator: no sign-up and no password reset by email.
    path('accounts/login/', auth_views.LoginView.as_view(), name='login'),
    path('accounts/logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('accounts/password/', PasswordChangeView.as_view(), name='password_change'),
    path('', include('prices.urls')),
]
