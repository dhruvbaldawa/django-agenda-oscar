"""
Django settings for django agenda demo
"""

from tests.settings import *  # noqa: F403,F401
from tests.settings import BASE_INSTALLED_APPS

INSTALLED_APPS = BASE_INSTALLED_APPS + [
    'tests.apps.AgendaDemoConfig']
