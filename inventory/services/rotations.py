import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from inventory.models import InstanceCredential
from inventory.services.crypto import decrypt_password, encrypt_password
from inventory.services.db_rotator import (
    change_database_password,
    verify_database_password,
)

logger = logging.getLogger(__name__)
RotationStatus = InstanceCredential.RotationStatus


def claim_rotation(
    credential_id: int,
    new_password: str | None = None,
) -> tuple[InstanceCredential, str, str] | None:
    """短事务认领凭据，持久化待应用的新密码"""
    with transaction.atomic():
        credential = (
            InstanceCredential.objects.select_for_update()
            .select_related("instance__cluster")
            .get(pk=credential_id)
        )

        if credential.status != RotationStatus.IDLE:
            return None

        old_password = decrypt_password(credential.encrypted_password)
        new_password = new_password or secrets.token_urlsafe(32)

        credential.pending_encrypted_password = encrypt_password(new_password)
        credential.status = RotationStatus.ROTATING
        credential.rotation_started_at = timezone.now()
        credential.save(
            update_fields=[
                "pending_encrypted_password",
                "status",
                "rotation_started_at",
                "updated_at",
            ],
        )

    return credential, old_password, new_password


def finalize_rotation(credential_id: int) -> bool:
    """目标库改密成功后，将 pending 密码提升为正式密码"""
    with transaction.atomic():
        credential = InstanceCredential.objects.select_for_update().get(
            pk=credential_id
        )

        if credential.status not in (
            RotationStatus.ROTATING,
            RotationStatus.FAILED,
        ):
            return False

        if not credential.pending_encrypted_password:
            return False

        credential.encrypted_password = credential.pending_encrypted_password
        credential.pending_encrypted_password = None
        credential.status = RotationStatus.IDLE
        credential.rotation_started_at = None
        credential.rotated_at = timezone.now()
        credential.save(
            update_fields=[
                "encrypted_password",
                "pending_encrypted_password",
                "status",
                "rotation_started_at",
                "rotated_at",
                "updated_at",
            ],
        )

    return True


def reset_rotation(credential_id: int) -> bool:
    """确认目标库未改密，清空 pending 并恢复 idle"""
    with transaction.atomic():
        credential = InstanceCredential.objects.select_for_update().get(
            pk=credential_id
        )

        if credential.status not in (
            RotationStatus.ROTATING,
            RotationStatus.FAILED,
        ):
            return False

        credential.pending_encrypted_password = None
        credential.status = RotationStatus.IDLE
        credential.rotation_started_at = None
        credential.save(
            update_fields=[
                "pending_encrypted_password",
                "status",
                "rotation_started_at",
                "updated_at",
            ],
        )

    return True


def mark_failed(credential_id: int) -> bool:
    """目标库状态无法确认，保留 pending；failed 允许后续恢复重试"""
    with transaction.atomic():
        credential = InstanceCredential.objects.select_for_update().get(
            pk=credential_id
        )

        if credential.status not in (
            RotationStatus.ROTATING,
            RotationStatus.FAILED,
        ):
            return False

        was_rotating = credential.status == RotationStatus.ROTATING
        credential.status = RotationStatus.FAILED
        credential.save(update_fields=["status", "updated_at"])

    return was_rotating


def execute_rotation(
    credential_id: int,
    new_password: str | None = None,
) -> bool:
    """认领 → 修改目标库 → finalize"""
    claimed = claim_rotation(credential_id, new_password)
    if claimed is None:
        return False

    credential, old_password, new_password = claimed
    instance = credential.instance

    # 失败时保留 rotating + pending，交给恢复流程判断目标库是否已改密。
    change_database_password(
        engine=instance.cluster.engine,
        host=instance.host,
        port=instance.port,
        dbname=instance.dbname,
        username=credential.username,
        old_password=old_password,
        new_password=new_password,
    )

    return finalize_rotation(credential_id)


def recover_stale_rotations(credential_id: int | None = None) -> int:
    """恢复卡在 rotating / failed 状态的凭据；返回成功处理的条数"""
    if credential_id is not None:
        credential_ids = [credential_id]
    else:
        cutoff = timezone.now() - timedelta(
            seconds=settings.CREDENTIAL_ROTATION_STALE_SECONDS,
        )
        credential_ids = list(
            InstanceCredential.objects.filter(
                status__in=(
                    RotationStatus.ROTATING,
                    RotationStatus.FAILED,
                ),
                rotation_started_at__lt=cutoff,
            ).values_list("pk", flat=True)
        )

    recovered = 0
    for cid in credential_ids:
        try:
            if recover_one(cid):
                recovered += 1
        except Exception:
            logger.exception(
                "恢复密码轮换状态失败，credential_id=%s",
                cid,
            )

    return recovered


def recover_one(credential_id: int) -> bool:
    credential = InstanceCredential.objects.select_related("instance__cluster").get(
        pk=credential_id
    )

    if credential.status not in (
        RotationStatus.ROTATING,
        RotationStatus.FAILED,
    ):
        return False

    instance = credential.instance

    if credential.pending_encrypted_password:
        try:
            pending_password = decrypt_password(
                credential.pending_encrypted_password,
            )
        except Exception:
            logger.exception(
                "待应用密码解密失败，credential_id=%s",
                credential_id,
            )
            return mark_failed(credential_id)

        if verify_database_password(
            engine=instance.cluster.engine,
            host=instance.host,
            port=instance.port,
            dbname=instance.dbname,
            username=credential.username,
            password=pending_password,
        ):
            return finalize_rotation(credential_id)

    try:
        old_password = decrypt_password(credential.encrypted_password)
    except Exception:
        logger.exception(
            "当前密码解密失败，credential_id=%s",
            credential_id,
        )
        return mark_failed(credential_id)

    if verify_database_password(
        engine=instance.cluster.engine,
        host=instance.host,
        port=instance.port,
        dbname=instance.dbname,
        username=credential.username,
        password=old_password,
    ):
        return reset_rotation(credential_id)

    return mark_failed(credential_id)
