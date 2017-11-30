#!/usr/bin/env python3
import os
from setuptools import setup

# Utility function to read the README file.
# Used for the long_description.  It's nice, because now 1) we have a top level
# README file and 2) it's easier to type in the README file than to put a raw
# string in below ...


def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()


setup(
    name='django-agenda',
    version='0.3',
    description='A scheduling app for Django.',
    long_description=read('README.rst'),
    author='Alan Trick',
    author_email='me@alantrick.ca',
    url='https://bitbucket.org/alantrick/django-agenda',
    packages=[
        'django_agenda',
        'django_agenda.migrations',
    ],
    include_package_data=True,
    zip_safe=False,  # everyone hates eggs
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Environment :: Web Environment',
        'Framework :: Django',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: GNU Lesser General Public License v3 or later (LGPLv3+)',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3.6',
        'Framework :: Django',
        'Framework :: Django :: 1.11',
        'Topic :: Utilities',
        'Topic :: Office/Business :: Scheduling',
    ],
    install_requires=[
        'Django>=1.11,<2.0',
        'django-recurrence',
        'django-timezone-field',
        'pytz',
    ],
    license='LGPL',
    test_suite='django_agenda.runtests.run_tests',
)
