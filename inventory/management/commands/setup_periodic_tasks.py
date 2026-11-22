from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django_celery_beat.models import (
    CrontabSchedule,
    IntervalSchedule,
    PeriodicTask,
)

DAILY_STATS_TASK = "inventory.tasks.collect_daily_instance_stats"
ROTATION_TASK = "inventory.tasks.rotate_instance_passwords"


class Command(BaseCommand):
    help = "创建或更新 django-celery-beat 的默认定时任务"

    @transaction.atomic
    def handle(self, *args, **options):
        daily_schedule, _ = CrontabSchedule.objects.get_or_create(
            minute="0",
            hour="0",
            day_of_week="*",
            day_of_month="*",
            month_of_year="*",
            timezone=settings.TIME_ZONE,
        )
        rotation_schedule, _ = IntervalSchedule.objects.get_or_create(
            every=12,
            period=IntervalSchedule.HOURS,
        )

        PeriodicTask.objects.update_or_create(
            name="collect-daily-instance-stats",
            defaults={
                "task": DAILY_STATS_TASK,
                "crontab": daily_schedule,
                "interval": None,
                "solar": None,
                "clocked": None,
                "enabled": True,
                "description": "每天 00:00 按部门和集群统计实例数量",
            },
        )
        PeriodicTask.objects.update_or_create(
            name="rotate-instance-passwords",
            defaults={
                "task": ROTATION_TASK,
                "interval": rotation_schedule,
                "crontab": None,
                "solar": None,
                "clocked": None,
                "enabled": True,
                "description": "每隔 12 小时随机轮换实例密码",
            },
        )

        self.stdout.write(self.style.SUCCESS("periodic tasks ready"))
        self.stdout.write("  collect-daily-instance-stats: crontab 0 0 * * *")
        self.stdout.write(f"  timezone: {settings.TIME_ZONE}")
        self.stdout.write("  rotate-instance-passwords: every 12 hours")
