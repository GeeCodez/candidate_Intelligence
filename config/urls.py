from django.contrib import admin
from django.urls import path
from core import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.index, name='index'),
    path('process-cv/', views.process_cv, name='process_cv'),
    path('verify-claim/', views.VerifyClaimView.as_view(), name='verify_claim'),
    path('verify-all-claims/', views.VerifyAllClaimsView.as_view(), name='verify_all_claims'),
]
