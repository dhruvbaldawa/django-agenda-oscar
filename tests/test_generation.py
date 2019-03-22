from datetime import date, datetime, time

import pytz
from django.contrib.auth.models import User
from django.test import TestCase

from django_agenda.time_span import TimeSpan
from django_agenda.models import get_free_times
from . import signals, models


def create_host():
    return User.objects.create(email='host@example.org', username="host")


class GenerationTestCase(TestCase):

    def setUp(self):
        signals.setup()
        self.host = create_host()

    def test_single_free(self):
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
        span = TimeSpan(pytz.utc.localize(datetime(2001, 3, 4, 20)),
                        pytz.utc.localize(datetime(2001, 3, 4, 22)))
        self.assertEqual(
            [span], get_free_times(self.host, span.start, span.end))

    def test_split_in_two(self):
        """
        If we create 3 availabilities that are right beside each other,
        we get one large free span, but if we remove the middle one, we
        end up with 2 again.
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
        third = models.Availability.objects.create(
            start_date=start,
            start_time=time(12),
            end_time=time(14),
            schedule=self.host,
            timezone=str(timezone),
        )
        for obj in (first, second, third):
            obj.recreate_occurrences(datetime(2002, 1, 8, tzinfo=timezone),
                                     datetime(2002, 1, 10, tzinfo=timezone))

        span = TimeSpan(pytz.utc.localize(datetime(2002, 1, 9, 16)),
                        pytz.utc.localize(datetime(2002, 1, 9, 22)))
        self.assertEqual(
            [span], get_free_times(self.host, span.start, span.end))

        second.delete()

        span_1 = TimeSpan(pytz.utc.localize(datetime(2002, 1, 9, 16)),
                          pytz.utc.localize(datetime(2002, 1, 9, 18)))
        span_2 = TimeSpan(pytz.utc.localize(datetime(2002, 1, 9, 20)),
                          pytz.utc.localize(datetime(2002, 1, 9, 22)))
        self.assertEqual(
            [span_1, span_2], get_free_times(self.host, span.start, span.end))


class GenerationBusyTestCase(TestCase):

    def setUp(self):
        signals.setup()
        self.host = create_host()
        self.span = TimeSpan(pytz.utc.localize(datetime(2002, 1, 9, 10)),
                             pytz.utc.localize(datetime(2002, 1, 9, 18)))
        obj = models.Availability.objects.create(
            start_date=self.span.start.date(),
            start_time=self.span.start.time(),
            end_time=self.span.end.time(),
            schedule=self.host,
            timezone=pytz.utc,
        )
        obj.recreate_occurrences(self.span.start, self.span.end)

        self.assertEqual(
            [self.span], get_free_times(
                self.host, self.span.start, self.span.end))

    def test_busy_infix(self):
        in_span = TimeSpan(pytz.utc.localize(datetime(2002, 1, 9, 12)),
                           pytz.utc.localize(datetime(2002, 1, 9, 13)))
        models.TimeSlot.objects.create(
            start=in_span.start, end=in_span.end, busy=True,
            schedule=self.host)

        spans = [TimeSpan(self.span.start, in_span.start),
                 TimeSpan(in_span.end, self.span.end)]
        self.assertEqual(
            spans, get_free_times(self.host, self.span.start, self.span.end))

    def test_busy_prefix(self):
        in_span = TimeSpan(pytz.utc.localize(datetime(2002, 1, 9, 8)),
                           pytz.utc.localize(datetime(2002, 1, 9, 12)))
        models.TimeSlot.objects.create(
            start=in_span.start, end=in_span.end, busy=True,
            schedule=self.host)

        spans = [TimeSpan(in_span.end, self.span.end)]
        self.assertEqual(
            spans, get_free_times(self.host, self.span.start, self.span.end))

    def test_busy_suffix(self):
        in_span = TimeSpan(pytz.utc.localize(datetime(2002, 1, 9, 12)),
                           pytz.utc.localize(datetime(2002, 1, 9, 20)))
        models.TimeSlot.objects.create(
            start=in_span.start, end=in_span.end, busy=True,
            schedule=self.host)

        spans = [TimeSpan(self.span.start, in_span.start)]
        self.assertEqual(
            spans, get_free_times(self.host, self.span.start, self.span.end))

    def test_double_infix(self):
        in_span_1 = TimeSpan(pytz.utc.localize(datetime(2002, 1, 9, 12)),
                             pytz.utc.localize(datetime(2002, 1, 9, 13)))
        in_span_2 = TimeSpan(pytz.utc.localize(datetime(2002, 1, 9, 13, 15)),
                             pytz.utc.localize(datetime(2002, 1, 9, 13, 30)))
        models.TimeSlot.objects.create(
            start=in_span_1.start, end=in_span_1.end, busy=True,
            schedule=self.host)
        models.TimeSlot.objects.create(
            start=in_span_2.start, end=in_span_2.end, busy=True,
            schedule=self.host)

        spans = [TimeSpan(self.span.start, in_span_1.start),
                 TimeSpan(in_span_1.end, in_span_2.start),
                 TimeSpan(in_span_2.end, self.span.end)]
        self.assertEqual(
            spans, get_free_times(self.host, self.span.start, self.span.end))

    def test_out_of_bounds(self):
        in_span = TimeSpan(pytz.utc.localize(datetime(2003, 1, 9, 12)),
                           pytz.utc.localize(datetime(2003, 1, 9, 20)))
        models.TimeSlot.objects.create(
            start=in_span.start, end=in_span.end, busy=True,
            schedule=self.host)

        spans = [TimeSpan(self.span.start, self.span.end)]
        self.assertEqual(
            spans, get_free_times(self.host, self.span.start, self.span.end))
