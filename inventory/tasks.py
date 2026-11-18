import logging
from datetime import date, timedelta

from celery import shared_task
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from inventory.models import Cluster, InstanceCredential, InstanceDailySnapshot
from inventory.services.rotations import execute_rotation, recover_stale_rotations

logger = logging.getLogger(__name__)


@shared_task
def collect_daily_instance_stats(snapshot_date: date | None = None) -> int:
    snapshot_date = snapshot_date or (timezone.localdate() - timedelta(days=1))

    clusters = Cluster.objects.filter(
        deleted_at__isnull=True,
    ).annotate(
        instance_count=Count(
            "instances",
            filter=Q(instances__deleted_at__isnull=True),
        ),
    )

    count = 0
    with transaction.atomic():
        for cluster in clusters:
            InstanceDailySnapshot.objects.update_or_create(
                snapshot_date=snapshot_date,
                cluster=cluster,
                defaults={
                    "department_id": cluster.department_id,
                    "instance_count": cluster.instance_count,
                },
            )
            count += 1

    return count


@shared_task
def rotate_instance_passwords() -> int:
    recover_stale_rotations()

    credential_ids = list(
        InstanceCredential.objects.filter(
            instance__deleted_at__isnull=True,
        ).values_list("pk", flat=True)
    )

    rotated = 0
    for credential_id in credential_ids:
        try:
            if execute_rotation(credential_id):
                rotated += 1
        except Exception:
            logger.exception(
                "数据库密码轮换失败：credential_id=%s",
                credential_id,
            )

    return rotated
