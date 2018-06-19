import contextlib
from datetime import datetime, timedelta
from typing import List

import django.utils.timezone
from django.conf import settings
from django.db import models
from django.utils.translation import ugettext_lazy as _

from django_agenda.models import (AbstractBooking, InvalidState, InvalidTime,
                                  TimeSlot, TimeSpan)


class Booking(AbstractBooking):
    DURATION = timedelta(minutes=60)

    guest = models.ForeignKey(
        verbose_name=_('guest'), to=settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT, related_name='+')
    host = models.ForeignKey(
        verbose_name=_('host'), to=settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT, related_name='+')
    assignee = models.ForeignKey(
        verbose_name=_('assignee'), to=settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, related_name='+',
        help_text='User responsible for responding to the booking')

    requested_time_1 = models.DateTimeField(
        verbose_name=_('requested time 1'), blank=True, null=True,
        db_index=True)
    requested_time_2 = models.DateTimeField(
        verbose_name=_('requested time 2'), blank=True, null=True,
        db_index=True)

    time_slots = models.ManyToManyField(
        verbose_name=_('time slot'), to=TimeSlot,
        through='BookingTime', through_fields=('booking', 'time_slot'),
        related_name='bookings')

    created_at = models.DateTimeField(
        _('created at'), auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(
        _('updated at'), auto_now=True, db_index=True)

    def __init__(self, *args, **kwargs):
        self.loading = True
        super().__init__(*args, **kwargs)
        self.loading = False
        self.__editor = None
        self.__super_editor = False
        self.allow_multiple_bookings = False

    def is_duplicate(self, other_booking):
        return (other_booking.host == self.host
                and other_booking.subject == self.subject
                and other_booking.guest == self.guest)

    def _get_padding(self):
        return timedelta(minutes=30)

    def _is_booked_slot_busy(self):
        return not self.allow_multiple_bookings

    def get_requested_times(self):
        for time in (self.requested_time_1, self.requested_time_2):
            if time is not None:
                yield time

    def get_reserved_spans(self) -> List[TimeSpan]:
        """
        Return a list of times that should be reserved
        """
        if self.state in self.RESERVED_STATES:
            for time in self.get_requested_times():
                yield (time, time + self.DURATION)

    # state change methods
    def cancel(self):
        raise NotImplementedError('Use `cancel_with_reason` instead')

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
        super().cancel()
        self.rejected_reason_public = reason
        self.rejected_reason_private = reason_private
        self.assignee = None

    def expire(self):
        if self.state != self.STATE_UNCONFIRMED:
            raise InvalidState('Booking must be unconfirmed')
        now = django.utils.timezone.now()
        for dt in (self.requested_time_1, self.requested_time_2):
            if dt > now:
                raise InvalidState(
                    'A booking must be in the past before it can be expired')

        self.state = self.STATE_EXPIRED

    def finish(self, has_happened: bool):
        if self.__editor is None:
            raise RuntimeError(
                'You must embed finish in a "with booking.set_editor()" call')
        if self.state != self.STATE_CONFIRMED:
            raise InvalidState('Booking must be confirmed')
        now = django.utils.timezone.now()
        for slot in self.time_slots.all():
            if slot.start > now:
                raise InvalidState(
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
            raise InvalidState('The other user has to confirm the booking')
        if time not in (self.requested_time_1, self.requested_time_2):
            raise InvalidTime('Must confirm an existing requested time')
        self.requested_time_1 = time
        self.requested_time_2 = None

        super().confirm(time)
        self.assignee = None

    def reschedule(self, new_times: List[datetime]):
        if len(new_times) < 1:
            raise InvalidTime(
                'Must supply at least one time when rescheduling, '
                'otherwise just cancel')
        if len(new_times) > 2:
            raise InvalidTime(
                'Only a maximum of 2 times is currently supported')

        if self.state == Booking.STATE_CONFIRMED:
            self.state = Booking.STATE_UNCONFIRMED
        elif self.state != Booking.STATE_UNCONFIRMED:
            raise InvalidState('Only unconfirmed bookings can be rescheduled')

        if self.__editor is None:
            raise RuntimeError(
                'You must embed reschedule in a '
                '"with booking.set_editor()" call')
        self.requested_time_1 = new_times[0]
        if len(new_times) > 1:
            self.requested_time_2 = new_times[1]
        if self.__editor == self.guest:
            self.assignee = self.host
        else:
            self.assignee = self.guest

    def _connect_slots(self, slots: List[TimeSlot]):
        records = [BookingTime(time_slot=slot, booking=self)
                   for slot in slots]
        BookingTime.objects.bulk_create(records)

    def _disconnect_slots(self, slots: TimeSlot):
        slot_ids = {slot.id for slot in slots}
        BookingTime.objects.filter(
            booking=self, time_slot_id__in=slot_ids).delete()

    def _book_unscheduled(self):
        """
        If this returns true, bookings will automatically create slots in
        unscheduled space.
        """
        return self.__super_editor or self.__editor == self.subject

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


class BookingTime(models.Model):

    class Meta:
        default_permissions = ()

    booking = models.ForeignKey(
        verbose_name=_('booking'), to=Booking, on_delete=models.PROTECT)
    time_slot = models.ForeignKey(
        verbose_name=_('time slot'), to=TimeSlot, on_delete=models.CASCADE)
