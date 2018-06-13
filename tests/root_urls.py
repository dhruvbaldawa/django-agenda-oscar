"""
URL patterns for testing app.

We don't have any for now.
"""
from django.conf.urls import include, url
from django.contrib import admin
from django.contrib.staticfiles.views import serve

from . import urls

urlpatterns = [

    url(r'^', include(urls)),
    url('^admin/', admin.site.urls),
] + [
    url(r'^static/(?P<path>.*)$', serve),
]
