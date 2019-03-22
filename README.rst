=============
Django Agenda
=============

|pipeline-badge| |coverage-badge| |pypi-badge|

Django agenda is a django app that allow you to create and book
times in a schedule. Our goal is to handle all the nasty details for
you; like timezones, schedule changes, and whether or not a
specific segment is actually available to be booked.

Installation
------------

First, install via pip (on Windows, replace ``pip3`` with ``pip``)

::

    pip3 install django-agenda
  
Then, edit your ``settings.py``, adding this line to ``INSTALLED_APPS``
  
::

   'django_agenda',

Features
--------

* Create recurring availabilities. We should support everything that
  RFC 2445 does.
* Subclass AbstractBooking to create bookings. Bookings will reserve
  time slots, and flag them as busy.
* Uses dynamic foreign keys, so you can relate your availabilities &
  bookings to anything (a user, an office space, a classroom)


.. |pipeline-badge| image:: https://gitlab.com/alantrick/django-agenda/badges/master/pipeline.svg
   :target: https://gitlab.com/alantrick/django-agenda/
   :alt: Build Status

.. |coverage-badge| image:: https://gitlab.com/alantrick/django-agenda/badges/master/coverage.svg
   :target: https://gitlab.com/alantrick/django-agenda/
   :alt: Coverage Status

.. |pypi-badge| image:: https://img.shields.io/pypi/v/django_agenda.svg
   :target: https://pypi.org/project/django-agenda/
   :alt: Project on PyPI

