from datetime import timedelta

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import signals
from django.utils import timezone

from django_agenda import models


def update_time_slots(sender, instance, created, raw, **_2):
    if raw:
        return
    assert sender == models.Availability
    start = timezone.now()
    # TODO: make this configurable
    end = start + timedelta(days=100)
    try:
        instance.recreate_occurrences(start, end)
    except ObjectDoesNotExist:
        return


def save_occurrence(sender, instance, created, raw, **_1):
    assert sender == models.AvailabilityOccurrence
    if created and not raw:
        try:
            instance.regen()
        except ObjectDoesNotExist:
            return


def delete_occurrence(sender, instance, *_1, **_2):
    assert sender == models.AvailabilityOccurrence
    instance.predelete()


def setup():
    signals.post_save.connect(update_time_slots, sender=models.Availability)
    signals.post_save.connect(
        save_occurrence, sender=models.AvailabilityOccurrence)
    signals.pre_delete.connect(
        delete_occurrence, sender=models.AvailabilityOccurrence)


def teardown():
    signals.post_save.disconnect(update_time_slots, sender=models.Availability)
    signals.post_save.disconnect(
        save_occurrence, sender=models.AvailabilityOccurrence)
    signals.pre_delete.disconnect(
        delete_occurrence, sender=models.AvailabilityOccurrence)
