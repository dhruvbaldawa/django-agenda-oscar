===============
Getting Started
===============

Installation
============

Getting the code
----------------

The recommended way to install django-agenda is via pip_ (on Windows,
replace ``pip3`` with ``pip``) ::

    $ pip3 install django-agenda

.. _pip: https://pip.pypa.io/


Configuring Django
------------------

Add ``"django_agenda"`` to your ``INSTALLED_APPS`` setting::

    INSTALLED_APPS = [
        # ...
        "django_agenda",
    ]



Concepts
========

Before we actually talk about any concepts, I'm going to bring up a bunch
of use-cases

   * Hovercraft Academy is a school, and it wants a system that will allow it
     to allocate the usage of their classrooms.
   * Eel Incorporated is a company. They want a system to manage their
     employees schedules so they know when they're busy and don't make
     overlapping meetings.

Second, let's talk about the ideas behind how the scheduling
system works from this perspective. There are two models that you must think
through when implementing this:

1. The “Schedule” model: This is the model that “owns” the schedule. It
   can be any type of model, even a built-in model like the user model from
   ``django.contrib.auth``. This model doesn't need to actually include any
   scheduling logic, it's just the thing that the schedule is attached to.
   Here's some examples:

   * For Hovercraft Academy, this would be the classrooms.
   * For Eal Incorporated, this would be the employees.

2. The “Booking” model: This is the model that reserves time from the
   schedule. This model is responsible for the majority of the configurable
   scheduling logic, like knowing what time, if any time at all, should be
   reserved, and if reserved times should be marked busy, and if busy times
   can overlap. Here's some examples:

   * For Hovercraft Academy, this would be a classroom reservation.
   * For Eal Incorporated, this would be the meetings.

There's also three other models that we'll cover shortly.


Creating & Linking Models
=========================

Django Agenda doesn’t provide models for you. We did in earlier versions, and
used contenttypes to link the models. That turned out to make for poor
usability and fragile code, since we couldn't trust the database to understand
anything. Instead, we provide a bunch of abstract base classes that you can
use to construct your models from.

First, you'll need to decide what your schedule model is. Here's an example
using Hovercraft Academy:

.. code-block:: python
   from django.db import models

   class Room(models.Model):
       number = models.SlugField(primary_key=True)

Second, you need to set up the 3 supporting models: Availability, Availability
Occurrence, and TimeSlot. The best way to do this, is to use the relevant
abstract classes, and specify a few special fields, so that the models can
find each other.

In order to help keep all our models straight, here's some pointers.

* Availabilities are what the end user sets. They can be set in any time zone
  and they can recur.
* Availability Occurrences are mostly for internal use. They're basically
  copies of Availabilities, but they don't recur.
* TimeSlots are the times that have already been blocked off from the
  Availabilities. As a general rule, a time is free if it is covered by the
  Availability Occurrences, and not covered by a busy TimeSlot.

Continuing our example:


.. code-block:: python

   from django_agenda.models import (AbstractAvailability,
                                     AbstractAvailabilityOccurrence,
                                     AbstractTimeSlot)

   class Availability(AbstractAvailability):
       class AgendaMeta:
           schedule_model = Room
           schedule_field = "room"  # optional


   class AvailabilityOccurrence(AbstractAvailabilityOccurrence):
       class AgendaMeta:
           availability_model = Availability
           schedule_model = Room
           schedule_field = "room"  # optional


   class TimeSlot(AbstractTimeSlot):
       class AgendaMeta:
           availability_model = Availability
           schedule_model = Room
           schedule_field = "room"  # optional


Finally, we need to make the booking class.

.. code-block:: python

   from django.db import models
   from django_agenda.models import AbstractBooking
   from django_agenda.time_span import TimeSpan

   class RoomReservation(AbstractBooking):
       class AgendaMeta:
           schedule_model = Room

       owner = models.ForeignKey(
           to=settings.AUTH_USER_MODEL,
           on_delete=models.PROTECT,
           related_name="reservations",
       )
       start_time = models.DateTimeField(db_index=True)
       end_time = models.DateTimeField(db_index=True)
       approved = models.BooleanField(default=False)

       def get_reserved_spans(self):
           # we only reserve the time if the reservation has been approved
           if self.approved:
               yield TimeSpan(self.start_time, self.end_time)

Now, we can do something like this:

.. code-block:: python

   import pytz
   from datetime import date, time, datetime

   start_date = date(2004, 1, 1)
   start_time = time(8)
   end_time = time(17)
   timezone = pytz.timezone('America/Vancouver')
   room = Room.objects.create(number='foo')
   # available from 8 AM to 5 PM
   Availability.objects.create(
       room=room,
       start_date=start_date,
       start_time=start_time,
       end_time=end_time,
       timezone=tz,
   )
   # reserve from 9-11
   reservation = RoomReservation(
       owner=<some user>,
       start_time=datetime(2004, 1, 1, 9, tzinfo=tz),
       end_time=datetime(2004, 1, 1, 11, tzinfo=tz),
   )
   # this will work
   reservation.clean()
   reservation.save()
   # reserve from 10-12
   reservation = RoomReservation(
       owner=<some user>,
       start_time=datetime(2004, 1, 1, 10, tzinfo=tz),
       end_time=datetime(2004, 1, 1, 12, tzinfo=tz),
   )
   # this won't work, time already reserved.
   reservation.clean()
