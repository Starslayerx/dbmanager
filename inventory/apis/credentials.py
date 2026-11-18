from django.db import transaction
from django.utils import timezone
from ninja import Router, Status

from inventory.models import DatabaseInstance, InstanceCredential
from inventory.schemas import CredentialIn, CredentialOut, ErrorOut
from inventory.services.crypto import encrypt_password
from inventory.services.rotations import execute_rotation


router = Router(tags=['实例凭据'])


@router.put(
    '/instances/{instance_id}/credential',
    response={
        200: CredentialOut,
        201: CredentialOut,
        (404, 409, 502): ErrorOut,
    },
)
def set_instance_credential(
    request,
    instance_id: int,
    payload: CredentialIn,
):
    """创建初始凭据，或对已有凭据修改密码"""
    created = False
    credential_pk = None

    with transaction.atomic():
        instance = DatabaseInstance.objects.select_for_update().filter(
            pk=instance_id,
            deleted_at__isnull=True,
        ).first()

        if instance is None:
            return Status(404, {
                'code': 'instance_not_found',
                'message': '数据库实例不存在或已删除',
            })

        credential = InstanceCredential.objects.select_for_update().filter(
            instance=instance,
        ).first()

        if credential is None:
            credential = InstanceCredential.objects.create(
                instance=instance,
                username=payload.username,
                encrypted_password=encrypt_password(payload.password),
                rotated_at=timezone.now(),
            )
            created = True
        else:
            if credential.status != InstanceCredential.RotationStatus.IDLE:
                return Status(409, {
                    'code': 'credential_rotating',
                    'message': '凭据正在轮换或已失败，请稍后重试',
                })

            if credential.username != payload.username:
                return Status(409, {
                    'code': 'credential_username_immutable',
                    'message': '已创建凭据的用户名不能直接修改',
                })

            credential_pk = credential.pk

    if created:
        return Status(201, credential)

    try:
        rotated = execute_rotation(credential_pk, payload.password)
    except InstanceCredential.DoesNotExist:
        return Status(404, {
            'code': 'credential_not_found',
            'message': '实例凭据不存在',
        })
    except Exception:
        return Status(502, {
            'code': 'database_password_rotation_failed',
            'message': '目标数据库改密失败',
        })

    if not rotated:
        return Status(409, {
            'code': 'credential_rotating',
            'message': '凭据正在轮换，请稍后重试',
        })

    credential = InstanceCredential.objects.get(pk=credential_pk)
    return Status(200, credential)


@router.get(
    '/instances/{instance_id}/credential',
    response={200: CredentialOut, 404: ErrorOut},
)
def get_instance_credential(request, instance_id: int):
    """查看实例凭据信息"""
    credential = InstanceCredential.objects.filter(
        instance_id=instance_id,
        instance__deleted_at__isnull=True,
    ).first()

    if credential is None:
        return Status(404, {
            'code': 'credential_not_found',
            'message': '实例凭据不存在',
        })

    return Status(200, credential)


@router.delete(
    '/instances/{instance_id}/credential',
    response={204: None, (404, 409): ErrorOut},
)
def delete_instance_credential(request, instance_id: int):
    """删除实例凭据"""
    with transaction.atomic():
        credential = InstanceCredential.objects.select_for_update().filter(
            instance_id=instance_id,
            instance__deleted_at__isnull=True,
        ).first()

        if credential is None:
            return Status(404, {
                'code': 'credential_not_found',
                'message': '实例凭据不存在',
            })

        if credential.status != InstanceCredential.RotationStatus.IDLE:
            return Status(409, {
                'code': 'credential_rotating',
                'message': '凭据正在轮换或已失败，请稍后重试',
            })

        credential.delete()

    return Status(204, None)
