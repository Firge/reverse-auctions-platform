"""
URL configuration for bidfall project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.urls import path
from django.contrib import admin
from rest_framework.routers import SimpleRouter
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
from . import views


router = SimpleRouter()
router.register('api/auction', views.AuctionViewSet, basename='auction')
router.register('api/auctions', views.AuctionViewSet, basename='auctions')

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/register/', views.RegisterView.as_view(), name='register'),
    path('api/auth/login/', TokenObtainPairView.as_view(), name='login'),
    path('api/auth/refresh/', TokenRefreshView.as_view(), name='refresh'),
    path('api/auth/me/', views.me_view, name='me'),
    path('api/auth/me/auctions/', views.my_auctions_view, name='me-auctions'),
    path('api/auth/me/participating-auctions/', views.my_participating_auctions_view, name='me-participating-auctions'),
    path('api/auth/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/server-time/', views.server_time_view, name='server-time'),
    path(
        'api/auctions/<int:pk>/bids/',
        views.AuctionViewSet.as_view({'get': 'bids', 'post': 'place_bid'}),
        name='auction-bids-create-alias',
    ),
]
urlpatterns += router.urls
