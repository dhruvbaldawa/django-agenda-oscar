from datetime import date, datetime, time

import pytz
from django.contrib.auth.models import User
from django.test import TestCase

from . import signals, models


def create_host():
    return User.objects.create(email='host@example.org', username="host")


class AvailabilitySingleTestCase(TestCase):

    def setUp(self):
        signals.setup()
        self.host = create_host()

    def test_add(self):
        timezone = pytz.timezone('America/Vancouver')
        obj = models.Availability.objects.create(
            start_date=date(2001, 3, 4),
            start_time=time(12),
            end_time=time(14),
            schedule=self.host,
            timezone=timezone,
        )
        obj.recreate_occurrences(datetime(2001, 3, 4, tzinfo=timezone),
                                 datetime(2001, 3, 6, tzinfo=timezone))
        slots = models.AvailabilityOccurrence.objects.filter(
            schedule=self.host)
        self.assertEqual(len(slots), 1)

    def test_multiple(self):
        """
        We can create multiple overlapping AvailabilityOccurrences
        """
        timezone = pytz.timezone('America/Vancouver')
        start = date(2002, 1, 9)
        first = models.Availability.objects.create(
            start_date=start,
            start_time=time(8),
            end_time=time(10),
            schedule=self.host,
            timezone=str(timezone),
        )
        second = models.Availability.objects.create(
            start_date=start,
            start_time=time(9, 30),
            end_time=time(12),
            schedule=self.host,
            timezone=str(timezone),
        )
        for obj in (first, second):
            obj.recreate_occurrences(datetime(2002, 1, 8, tzinfo=timezone),
                                     datetime(2002, 4, 18, tzinfo=timezone))

        occurrences = models.AvailabilityOccurrence.objects.filter(
            schedule=self.host)
        self.assertEqual(len(occurrences.all()), 2)
