from datetime import timedelta

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import signals
from django.utils import timezone

from .models import Availability


def update_time_slots(sender, instance, created, raw, **_2):
    if raw:
        return
    assert sender == Availability
    start = timezone.now()
    end = start + timedelta(days=100)
    try:
        instance.recreate_occurrences(start, end)
    except ObjectDoesNotExist:
        return


def setup():
    signals.post_save.connect(update_time_slots, sender=Availability)


def teardown():
    signals.post_save.disconnect(update_time_slots, sender=Availability)
