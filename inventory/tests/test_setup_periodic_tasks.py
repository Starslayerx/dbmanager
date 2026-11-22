import pytest
from django.conf import settings
from django.core.management import call_command
from django_celery_beat.models import (
    CrontabSchedule,
    IntervalSchedule,
    PeriodicTask,
)

pytestmark = pytest.mark.django_db

TASK_NAMES = (
    "collect-daily-instance-stats",
    "rotate-instance-passwords",
)


def test_setup_periodic_tasks_creates_tasks():
    call_command("setup_periodic_tasks")

    daily = PeriodicTask.objects.get(name="collect-daily-instance-stats")
    assert daily.task == "inventory.tasks.collect_daily_instance_stats"
    assert daily.enabled is True
    assert daily.crontab.minute == "0"
    assert daily.crontab.hour == "0"
    assert str(daily.crontab.timezone) == settings.TIME_ZONE

    rotation = PeriodicTask.objects.get(name="rotate-instance-passwords")
    assert rotation.task == "inventory.tasks.rotate_instance_passwords"
    assert rotation.enabled is True
    assert rotation.interval.every == 12
    assert rotation.interval.period == IntervalSchedule.HOURS


def test_setup_periodic_tasks_is_idempotent():
    call_command("setup_periodic_tasks")
    call_command("setup_periodic_tasks")

    assert PeriodicTask.objects.filter(name__in=TASK_NAMES).count() == 2
    assert (
        CrontabSchedule.objects.filter(
            minute="0",
            hour="0",
            day_of_week="*",
            day_of_month="*",
            month_of_year="*",
            timezone=settings.TIME_ZONE,
        ).count()
        == 1
    )
    assert (
        IntervalSchedule.objects.filter(
            every=12,
            period=IntervalSchedule.HOURS,
        ).count()
        == 1
    )
