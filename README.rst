=============
Django Agenda
=============


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
* Automatically generate time slots from availabilities. This handles
  overlapping availabilities, timezones, and joining adjacent slots.
* Subclass AbstractBooking to create bookings. Bookings will reserve
  time slots, and flag them as busy.
* Uses generic foreign keys, so you can relate your availabilities &
  bookings to anything (a user, an office space, a classroom)

