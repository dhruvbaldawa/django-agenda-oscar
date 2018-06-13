"""
Django settings for django_agenda tests
"""
# based of django-debug-toolbar
# https://github.com/jazzband/django-debug-toolbar/blob/master/tests/settings.py
import os

BASE_DIR = os.path.dirname(os.path.dirname(__file__))


# Quick-start development settings - unsuitable for production

SECRET_KEY = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890'

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'recurrence',
    'django_agenda',
]
