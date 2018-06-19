# -*- coding: utf-8 -*-
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('django_agenda', '0002_index'),
    ]

    operations = [
        migrations.AddField(
            model_name='timeslot',
            name='padding_for',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=models.deletion.CASCADE,
                related_name='padded_by', to='django_agenda.TimeSlot')),
        migrations.RemoveField(
            model_name='timeslot',
            name='slot_before',
        ),
        migrations.RemoveField(
            model_name='timeslot',
            name='slot_after',
        ),
    ]
