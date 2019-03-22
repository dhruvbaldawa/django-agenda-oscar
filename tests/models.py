import contextlib
from datetime import datetime, timedelta
from typing import List

import django.utils.timezone
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import ugettext_lazy as _

from django_agenda.time_span import TimeSpan
from django_agenda.models import (
    AbstractAvailability, AbstractAvailabilityOccurrence,
    AbstractTimeSlot, AbstractBooking)


class Availability(AbstractAvailability):
    class AgendaMeta:
        schedule_model = settings.AUTH_USER_MODEL
        schedule_field = 'schedule'


class AvailabilityOccurrence(AbstractAvailabilityOccurrence):
    class AgendaMeta:
        availability_model = Availability
        schedule_model = settings.AUTH_USER_MODEL
        schedule_field = 'schedule'


class TimeSlot(AbstractTimeSlot):
    class AgendaMeta:
        schedule_model = settings.AUTH_USER_MODEL
        schedule_field = 'schedule'
        availability_model = Availability


class Booking(AbstractBooking):

    class AgendaMeta:
        schedule_model = settings.AUTH_USER_MODEL
        schedule_field = 'schedule'

    DURATION = timedelta(minutes=60)

    guest = models.ForeignKey(
        verbose_name=_('guest'), to=settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT, related_name='+')
    assignee = models.ForeignKey(
        verbose_name=_('assignee'), to=settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, blank=True, null=True, related_name='+',
        help_text='User responsible for responding to the booking')

    requested_time_1 = models.DateTimeField(
        verbose_name=_('requested time 1'), blank=True, null=True,
        db_index=True)
    requested_time_2 = models.DateTimeField(
        verbose_name=_('requested time 2'), blank=True, null=True,
        db_index=True)

    padding = models.DurationField(
        verbose_name=_('padding'), default=timedelta(minutes=30))

    created_at = models.DateTimeField(
        _('created at'), auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(
        _('updated at'), auto_now=True, db_index=True)

    STATE_UNCONFIRMED = 'UNC'
    # this means it's either scheduled to happen
    # or has just happened and hasn't been moved
    # to
    STATE_CONFIRMED = 'CNF'
    STATE_DECLINED = 'DCL'
    STATE_COMPLETED = 'CMP'
    STATE_CANCELED = 'CAN'
    # expired is for things that haven't been confirmed
    STATE_EXPIRED = 'EXP'
    # missed means that it was confirmed, but nobody showed
    STATE_MISSED = 'MIS'

    STATES = (
        (STATE_UNCONFIRMED, 'Unconfirmed'),
        (STATE_DECLINED, 'Declined'),
        (STATE_EXPIRED, 'Expired'),
        (STATE_CONFIRMED, 'Confirmed'),
        (STATE_COMPLETED, 'Completed'),
        (STATE_CANCELED, 'Canceled'),
        (STATE_MISSED, 'Missed'),
    )
    # states in which the time slots stay reserved.
    RESERVED_STATES = (STATE_UNCONFIRMED, STATE_CONFIRMED, STATE_COMPLETED,
                       STATE_MISSED)

    state = models.CharField(
        max_length=3, db_index=True,
        choices=STATES, default=STATE_UNCONFIRMED)

    def __init__(self, *args, **kwargs):
        self.loading = True
        super().__init__(*args, **kwargs)
        self.loading = False
        self.__editor = None
        self.__super_editor = False
        self.allow_multiple_bookings = False

    def clean(self):
        super().clean()
        # check for duplicates
        dup_q = models.Q(schedule=self.schedule, guest=self.guest,
                         state=self.state)
        if self.id is not None:
            dup_q &= ~models.Q(id=self.id)

        sub_q = models.Q()
        if self.requested_time_1 is not None:
            sub_q |= models.Q(requested_time_1=self.requested_time_1) | \
                     models.Q(requested_time_2=self.requested_time_1)
        if self.requested_time_2 is not None:
            sub_q |= models.Q(requested_time_1=self.requested_time_2) | \
                     models.Q(requested_time_2=self.requested_time_2)
        dup_q &= sub_q

        if Booking.objects.filter(dup_q).exists():
            raise ValidationError(_('Duplicate booking'))

    def _get_padding(self):
        return self.padding

    def _is_booked_slot_busy(self):
        return not self.allow_multiple_bookings

    def get_requested_times(self):
        for time in (self.requested_time_1, self.requested_time_2):
            if time is not None:
                yield time

    def get_reserved_spans(self):
        """
        Return a list of times that should be reserved
        """
        if self.state in self.RESERVED_STATES:
            for time in self.get_requested_times():
                yield TimeSpan(time, time + self.DURATION)

    # state change methods
    def cancel_with_reason(self, reason, reason_private):
        """
        Cancel a booking

        In order to cancel a booking it must be either in the unconfirmed
        or confirmed state. Bookings in other states have no need to be
        canceled.
        """
        if self.__editor is None:
            raise RuntimeError(
                'You must embed cancel in a "with booking.set_editor()" call')
        if self.state == Booking.STATE_UNCONFIRMED:
            self.state = Booking.STATE_DECLINED
        elif self.state == Booking.STATE_CONFIRMED:
            self.state = Booking.STATE_CANCELED
        else:
            raise ValidationError(
                'Only unconfirmed & unconfirmed bookings can be canceled')
        self.state = Booking.STATE_CANCELED
        self.rejected_reason_public = reason
        self.rejected_reason_private = reason_private
        self.assignee = None

    def expire(self):
        if self.state != self.STATE_UNCONFIRMED:
            raise ValidationError('Booking must be unconfirmed')
        now = django.utils.timezone.now()
        for dt in (self.requested_time_1, self.requested_time_2):
            if dt > now:
                raise ValidationError(
                    'A booking must be in the past before it can be expired')

        self.state = self.STATE_EXPIRED

    def finish(self, has_happened: bool):
        if self.__editor is None:
            raise RuntimeError(
                'You must embed finish in a "with booking.set_editor()" call')
        if self.state != self.STATE_CONFIRMED:
            raise ValidationError('Booking must be confirmed')
        now = django.utils.timezone.now()
        for slot in self.time_slots.all():
            if slot.start > now:
                raise ValidationError(
                    'A booking must have started before it can be finished')

        if has_happened:
            self.state = self.STATE_COMPLETED
        else:
            self.state = self.STATE_MISSED

    def confirm(self, time: datetime):
        if self.__editor is None:
            raise RuntimeError(
                'You must embed confirm in a "with booking.set_editor()" call')
        if self.assignee is not None and self.__editor != self.assignee:
            raise ValidationError('The other user has to confirm the booking')
        if time not in (self.requested_time_1, self.requested_time_2):
            raise ValidationError('Must confirm an existing requested time')
        self.requested_time_1 = time
        self.requested_time_2 = None
        self.state = Booking.STATE_CONFIRMED
        self.assignee = None

    def reschedule(self, new_times: List[datetime]):
        if len(new_times) < 1:
            raise ValidationError(
                'Must supply at least one time when rescheduling, '
                'otherwise just cancel')
        if len(new_times) > 2:
            raise ValidationError(
                'Only a maximum of 2 times is currently supported')

        if self.state == Booking.STATE_CONFIRMED:
            self.state = Booking.STATE_UNCONFIRMED
        elif self.state != Booking.STATE_UNCONFIRMED:
            raise ValidationError(
                'Only unconfirmed bookings can be rescheduled')

        if self.__editor is None:
            raise RuntimeError(
                'You must embed reschedule in a '
                '"with booking.set_editor()" call')
        self.requested_time_1 = new_times[0]
        if len(new_times) > 1:
            self.requested_time_2 = new_times[1]
        if self.__editor == self.guest:
            self.assignee = self.schedule
        else:
            self.assignee = self.guest

    def _book_unscheduled(self):
        """
        If this returns true, bookings will automatically create slots in
        unscheduled space.
        """
        return self.__super_editor or self.__editor == self.schedule

    @contextlib.contextmanager
    def set_super_editor(self):
        assert not self.__super_editor
        assert self.__editor is None
        self.__super_editor = True
        yield
        self.__super_editor = False

    @contextlib.contextmanager
    def set_editor(self, user):
        assert self.__editor is None
        self.__editor = user
        yield
        self.__editor = None

    def __str__(self):
        return '<Booking: {}>'.format(self.id)


def recreate_time_slots(start=None, end=None):
    """Remove all the time slots and start from scratch

    New time slots are created between start & end inclusive
    """
    if start is None:
        start = django.utils.timezone.now()
    if end is None:
        end = start + timedelta(days=100)

    for availability in Availability.objects.all():
        availability.recreate_occurrences(start, end)
