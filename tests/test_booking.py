from datetime import datetime, time, timedelta

import pytz
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase

from . import signals, models


class BaseCase(TestCase):

    def check_time_slots(self, expected_data, slots):
        min_len = min(len(expected_data), len(slots))
        for idx, (start, end, busy) in enumerate(expected_data):
            if not idx < min_len:
                break
            self.assertEqual(
                start, (slots[idx].start + self.offset).time(),
                'Slot {} did not have the right start time'.format(idx))
            self.assertEqual(
                end, (slots[idx].end + self.offset).time(),
                'Slot {} did not have the right end time'.format(idx))
            self.assertEqual(
                busy, slots[idx].busy,
                'Slot {} did not have the right busy state'.format(idx))
        self.assertEqual(
            len(expected_data), len(slots), 'Incorrect number of slots')


class BookingTests(BaseCase):

    def setUp(self):
        """
        Test the ability of a booking to divide time slots

        In this test we create a large availability, and then do a booking
        inside it. The result is that the time slot should get split up.
        """
        self.timezone = pytz.timezone('America/Vancouver')
        self.birthday = datetime(1984, 12, 11, tzinfo=self.timezone)
        signals.setup()
        self.host = User.objects.create(
            email='host@example.org', username="host")
        self.availability = models.Availability.objects.create(
            start_date=self.birthday.date(),
            start_time=time(8),
            end_time=time(14),
            schedule=self.host,
            timezone=str(self.timezone)
        )
        self.offset = self.timezone.utcoffset(datetime(1984, 12, 11))
        self.availability.recreate_occurrences(
            self.birthday, self.birthday + timedelta(days=1))
        aos = models.AvailabilityOccurrence.objects.filter(
            schedule=self.host)
        self.assertEqual(len(aos), 1)

        self.guest = User.objects.create(
            email='guest@example.org', username="guest")
        self.second_guest = User.objects.create(
            email='second_guest@example.org', username="second_guest")
        self.booking_time = pytz.utc.localize(
            datetime.combine(self.birthday.date(), time(11)) - self.offset)
        self.booking = models.Booking(
            guest=self.guest,
            schedule=self.host,
            requested_time_1=self.booking_time,
        )
        self.booking.clean()
        self.booking.save()
        # This should result in 5 time slots:
        # * 10:30-11  padding
        # * 11-12     booking
        # * 12-12:30  padding
        slots = models.TimeSlot.objects.filter(
            schedule=self.host).order_by('start')
        times = ((time(10, 30), time(11), True),
                 (time(11), time(12), True),
                 (time(12), time(12, 30), True))
        self.check_time_slots(times, slots)

    def test_create_slots(self):
        """
        The host can create a booking in a space with no availabilities
        """
        booking = models.Booking(
            guest=self.guest,
            schedule=self.host,
            requested_time_1=(self.booking_time + timedelta(days=1)),
        )
        with self.assertRaises(ValidationError):
            booking.full_clean()
            booking.save()

        with booking.set_editor(self.host):
            booking.full_clean()
            booking.save()

    def test_add_overlapping_booking(self):
        """
        Create a booking, and then create another one 30 minutes earlier.

        The second booking should fail to create.
        """
        overlapping_booking = models.Booking(
            guest=self.guest,
            schedule=self.host,
            requested_time_1=self.booking_time - timedelta(minutes=30),
        )
        with self.assertRaises(ValidationError):
            overlapping_booking.full_clean()
            overlapping_booking.save()

    def test_booking_reschedule(self):
        with self.booking.set_editor(self.guest):
            self.booking.reschedule(
                [self.booking_time - timedelta(hours=1)])
            self.booking.full_clean()
            self.booking.save()

        # This should result in 3 time slots:
        # * 9:30-10  padding
        # * 10-11     booking
        # * 11-11:30  padding

        slots = models.TimeSlot.objects.filter(
            schedule=self.host).order_by('start')
        times = ((time(9, 30), time(10), True),
                 (time(10), time(11), True),
                 (time(11), time(11, 30), True))
        self.check_time_slots(times, slots)

        booking_slots = self.booking.time_slots.all()
        self.assertEqual(len(booking_slots), 1)

    def test_disallow_multiple_bookings(self):
        self.host.save()
        multiple_booking = models.Booking(
            guest=self.guest,
            schedule=self.host,
            requested_time_1=self.booking_time - timedelta(hours=2),
        )
        multiple_booking.full_clean()
        multiple_booking.save()
        second_multiple_booking = models.Booking(
            guest=self.second_guest,
            schedule=self.host,
            requested_time_1=self.booking_time - timedelta(hours=2),
        )
        # Now we should not be able to create another booking at the same time
        with self.assertRaises(ValidationError):
            second_multiple_booking.full_clean()
            second_multiple_booking.save()

    def test_multiple_booking_cancel(self):
        self.host.save()
        multiple_booking = models.Booking(
            guest=self.guest,
            schedule=self.host,
            requested_time_1=self.booking_time - timedelta(hours=2),
        )
        multiple_booking.allow_multiple_bookings = True
        multiple_booking.full_clean()
        multiple_booking.save()
        slots = models.TimeSlot.objects.filter(
            schedule=self.host).order_by('start')
        # Now we should be able to create another booking at the same time
        second_multiple_booking = models.Booking(
            guest=self.second_guest,
            schedule=self.host,
            requested_time_1=self.booking_time - timedelta(hours=2),
        )
        second_multiple_booking.allow_multiple_bookings = True
        second_multiple_booking.full_clean()
        second_multiple_booking.save()
        with multiple_booking.set_editor(self.host):
            multiple_booking.cancel_with_reason('foo', 'bar')
            multiple_booking.full_clean()
            multiple_booking.save()
        times = ((time(8, 30), time(9), True),
                 (time(9), time(10), False),  # multiple booking slot
                 (time(10), time(10, 30), True),
                 (time(10, 30), time(11), True),
                 (time(11), time(12, 00), True),  # original booking slot
                 (time(12), time(12, 30), True))
        self.check_time_slots(times, slots)
        with second_multiple_booking.set_editor(self.host):
            second_multiple_booking.cancel_with_reason('foo', 'bar')
            second_multiple_booking.full_clean()
            second_multiple_booking.save()
        slots = models.TimeSlot.objects.filter(
            schedule=self.host).order_by('start')
        times = ((time(10, 30), time(11), True),
                 (time(11), time(12, 00), True),  # original booking slot
                 (time(12), time(12, 30), True))
        self.check_time_slots(times, slots)

    def test_multiple_bookings(self):
        self.host.save()
        multiple_booking = models.Booking(
            guest=self.guest,
            schedule=self.host,
            requested_time_1=self.booking_time - timedelta(hours=2),
        )
        multiple_booking.allow_multiple_bookings = True
        multiple_booking.full_clean()
        multiple_booking.save()
        slots = models.TimeSlot.objects.filter(
            schedule=self.host).order_by('start')
        times = ((time(8, 30), time(9), True),
                 (time(9), time(10), False),  # multiple booking slot
                 (time(10), time(10, 30), True),
                 (time(10, 30), time(11), True),
                 (time(11), time(12, 00), True),  # original booking slot
                 (time(12), time(12, 30), True))
        self.check_time_slots(times, slots)
        # Now we should be able to create another booking at the same time
        second_multiple_booking = models.Booking(
            guest=self.guest,
            schedule=self.host,
            requested_time_1=self.booking_time - timedelta(hours=2),
        )
        second_multiple_booking.allow_multiple_bookings = True
        # check for duplicate, that is not allowed
        with self.assertRaises(ValidationError):
            second_multiple_booking.full_clean()
            second_multiple_booking.save()
        # a booking in an offset time should fail
        second_multiple_booking.guest = self.second_guest
        second_multiple_booking.requested_time_1 = \
            self.booking_time - timedelta(hours=2, minutes=30)
        with self.assertRaises(ValidationError):
            second_multiple_booking.full_clean()
            second_multiple_booking.save()
        # set it back to the overlapping spot, and this should work
        second_multiple_booking.requested_time_1 = \
            self.booking_time - timedelta(hours=2)
        second_multiple_booking.full_clean()
        second_multiple_booking.save()
        slots = models.TimeSlot.objects.filter(
            schedule=self.host).order_by('start')
        times = ((time(8, 30), time(9), True),  # padding 1
                 (time(8, 30), time(9), True),  # padding 2
                 (time(9), time(10), False),  # multiple booking 1
                 (time(9), time(10), False),  # multiple booking 2
                 (time(10), time(10, 30), True),  # padding 1
                 (time(10), time(10, 30), True),  # padding 2
                 (time(10, 30), time(11), True),
                 (time(11), time(12, 00), True),  # original booking slot
                 (time(12), time(12, 30), True))
        self.check_time_slots(times, slots)

    def test_cancel(self):
        other_booking_time = self.booking_time - timedelta(minutes=90)
        other_booking = models.Booking(
            guest=self.guest,
            schedule=self.host,
            requested_time_1=other_booking_time
        )
        other_booking.full_clean()
        other_booking.save()
        with other_booking.set_editor(self.host):
            other_booking.confirm(other_booking_time)
            other_booking.full_clean()
            other_booking.save()
        with self.booking.set_editor(self.guest):
            self.booking.confirm(self.booking_time)
            self.booking.full_clean()
            self.booking.save()

        with other_booking.set_editor(self.host):
            other_booking.cancel_with_reason('foo', 'bar')
            other_booking.full_clean()
            other_booking.save()
        with self.booking.set_editor(self.guest):
            self.booking.cancel_with_reason('foo', 'bar')
            self.booking.full_clean()
            self.booking.save()
        # we've cancelled all the times, so there should be no slots
        times = []
        slots = models.TimeSlot.objects.filter(
            schedule=self.host).order_by('start')
        self.check_time_slots(times, slots)


class AdvancedBookingTests(BaseCase):

    def setUp(self):
        """
        Test the ability of a booking to divide time slots

        In this test we create a large availability, and then do a booking
        inside it. The result is that the time slot should get split up.
        """
        self.timezone = pytz.timezone('America/Vancouver')
        self.date = datetime(1990, 3, 3, tzinfo=self.timezone)
        signals.setup()
        self.host = User.objects.create(
            email='host@example.org', username="host")
        self.offset = self.timezone.utcoffset(datetime(1990, 3, 3))

    def test_padding_changes(self):
        """
        If a booking's padding changes, it's important to regenerate the
        padded (and other affected) slots so that we don't display bad data.
        """
        # create an availability to use
        avail = models.Availability.objects.create(
            start_date=self.date.date(),
            start_time=time(8),
            end_time=time(14),
            schedule=self.host,
            timezone=str(self.timezone)
        )
        avail.recreate_occurrences(
            self.date, self.date + timedelta(days=10))
        slots = models.TimeSlot.objects.filter(schedule=self.host)
        times = []
        self.check_time_slots(times, slots)

        self.guest = User.objects.create(
            email='guest@example.org', username="guest")
        booking_time = pytz.utc.localize(
            datetime.combine(avail.start_date, time(11)) - self.offset)
        booking = models.Booking.objects.create(
            guest=self.guest,
            schedule=self.host,
            requested_time_1=booking_time,
        )
        slots = models.TimeSlot.objects.filter(
            schedule=self.host).order_by('start')
        #  They'll be the usual 3 slots
        # * 10:30-11
        # * 11-12
        # * 12-12:30
        times = ((time(10, 30), time(11), True),
                 (time(11), time(12), True),
                 (time(12), time(12, 30), True))
        self.check_time_slots(times, slots)
        # now change the padding
        booking.padding = timedelta(hours=1)
        booking.full_clean()
        booking.save()
        slots = models.TimeSlot.objects.filter(
            schedule=self.host).order_by('start')
        # this should still be the same as before because the booking shouldn't
        # necessarily know about the padding
        self.check_time_slots(times, slots)
        booking._padding_changed()
        slots = models.TimeSlot.objects.filter(
            schedule=self.host).order_by('start')
        #  Now the padding will be 1 hour
        # * 8-10
        # * 10-11
        # * 11-12
        # * 12-13
        # * 13-14
        times = ((time(10), time(11), True),
                 (time(11), time(12), True),
                 (time(12), time(13), True))
        self.check_time_slots(times, slots)

    def test_multiple_request_times(self):
        first_avail = models.Availability.objects.create(
            start_date=self.date.date(),
            start_time=time(8),
            end_time=time(14),
            schedule=self.host,
            timezone=str(self.timezone)
        )
        second_avail = models.Availability.objects.create(
            start_date=datetime(1990, 3, 5, tzinfo=self.timezone).date(),
            start_time=time(8),
            end_time=time(14),
            schedule=self.host,
            timezone=str(self.timezone)
        )

        for avail in (first_avail, second_avail):
            avail.recreate_occurrences(
                self.date, self.date + timedelta(days=10))
        slots = models.TimeSlot.objects.filter(schedule=self.host)
        times = []
        self.check_time_slots(times, slots)

        self.guest = User.objects.create(
            email='guest@example.org', username="guest")
        first_booking_time = pytz.utc.localize(
            datetime.combine(first_avail.start_date, time(11)) - self.offset)
        second_booking_time = pytz.utc.localize(
            datetime.combine(second_avail.start_date, time(11)) - self.offset)

        b = models.Booking(
            guest=self.guest,
            schedule=self.host,
            requested_time_2=second_booking_time,
            requested_time_1=first_booking_time,
        )
        b.full_clean()
        b.save()
        slots = models.TimeSlot.objects.filter(
            schedule=self.host).order_by('start')
        times = ((time(10, 30), time(11), True),  # first time pad
                 (time(11), time(12), True),  # first time
                 (time(12), time(12, 30), True),  # first time pad
                 (time(10, 30), time(11), True),
                 (time(11), time(12), True),
                 (time(12), time(12, 30), True))
        self.check_time_slots(times, slots)
