"""
Django settings for api documentation generation
"""
import os
import sys

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), os.pardir))

DEBUG = True
TEMPLATE_DEBUG = DEBUG

DATABASES = {
    "default": {
        "NAME": ":memory:",
        "ENGINE": "django.db.backends.sqlite3",
        "USER": "",
        "PASSWORD": "",
        "PORT": "",
    }
}

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django_agenda",
]

SECRET_KEY = "test"
