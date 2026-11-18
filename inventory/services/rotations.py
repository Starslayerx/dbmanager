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
            InstanceCredential.objects
            .select_for_update()
            .select_related('instance__cluster')
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
                'pending_encrypted_password',
                'status',
                'rotation_started_at',
                'updated_at',
            ],
        )

    return credential, old_password, new_password


def finalize_rotation(credential_id: int) -> bool:
    """目标库改密成功后，将 pending 密码提升为正式密码"""
    with transaction.atomic():
        credential = (
            InstanceCredential.objects
            .select_for_update()
            .get(pk=credential_id)
        )

        if credential.status != RotationStatus.ROTATING:
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
                'encrypted_password',
                'pending_encrypted_password',
                'status',
                'rotation_started_at',
                'rotated_at',
                'updated_at',
            ],
        )

    return True


def reset_rotation(credential_id: int) -> bool:
    """确认目标库未改密，清空 pending 并恢复 idle"""
    with transaction.atomic():
        credential = (
            InstanceCredential.objects
            .select_for_update()
            .get(pk=credential_id)
        )

        if credential.status != RotationStatus.ROTATING:
            return False

        credential.pending_encrypted_password = None
        credential.status = RotationStatus.IDLE
        credential.rotation_started_at = None
        credential.save(
            update_fields=[
                'pending_encrypted_password',
                'status',
                'rotation_started_at',
                'updated_at',
            ],
        )

    return True


def mark_failed(credential_id: int) -> bool:
    """目标库状态无法确认，保留 pending，等待人工处理"""
    with transaction.atomic():
        credential = (
            InstanceCredential.objects
            .select_for_update()
            .get(pk=credential_id)
        )

        if credential.status != RotationStatus.ROTATING:
            return False

        credential.status = RotationStatus.FAILED
        credential.save(update_fields=['status', 'updated_at'])

    return True


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

    try:
        change_database_password(
            engine=instance.cluster.engine,
            host=instance.host,
            port=instance.port,
            dbname=instance.dbname,
            username=credential.username,
            old_password=old_password,
            new_password=new_password,
        )
    except Exception:
        # 保留 rotating + pending，交给恢复流程判断目标库是否已改密。
        raise

    return finalize_rotation(credential_id)


def recover_stale_rotations(credential_id: int | None = None) -> int:
    """恢复卡在 rotating 状态的凭据；返回成功处理的条数"""
    if credential_id is not None:
        credential_ids = [credential_id]
    else:
        cutoff = timezone.now() - timedelta(
            seconds=settings.CREDENTIAL_ROTATION_STALE_SECONDS,
        )
        credential_ids = list(
            InstanceCredential.objects.filter(
                status=RotationStatus.ROTATING,
                rotation_started_at__lt=cutoff,
            ).values_list('pk', flat=True)
        )

    recovered = 0
    for cid in credential_ids:
        try:
            if recover_one(cid):
                recovered += 1
        except Exception:
            logger.exception(
                '恢复密码轮换状态失败，credential_id=%s',
                cid,
            )

    return recovered


def recover_one(credential_id: int) -> bool:
    credential = (
        InstanceCredential.objects
        .select_related('instance__cluster')
        .get(pk=credential_id)
    )

    if credential.status != RotationStatus.ROTATING:
        return False

    instance = credential.instance

    if credential.pending_encrypted_password:
        try:
            pending_password = decrypt_password(
                credential.pending_encrypted_password,
            )
        except Exception:
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
