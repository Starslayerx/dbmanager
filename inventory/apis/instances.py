from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from ninja import Router, Status
from ninja.pagination import PageNumberPagination, paginate
from psycopg.errors import ForeignKeyViolation, UniqueViolation

from inventory.models import Cluster, DatabaseInstance as Instance
from inventory.probes import tcp_probe
from inventory.schemas import (
    InstanceIn,
    InstanceOut,
    ErrorOut,
    ProbeOut,
    ValidationErrorOut,
)


router = Router(tags=['实例'])

@router.get('/instances', response=list[InstanceOut])
@paginate(PageNumberPagination, page_size=20)
def list_instances(request, cluster_id: int | None = None):
    """获取数据库实例列表"""
    queryset = Instance.objects.filter(
        deleted_at__isnull=True
    ).order_by('id')
    if cluster_id is not None:
        queryset = queryset.filter(cluster_id=cluster_id)

    return queryset


@router.get(
    '/instances/{instance_id}',
    response={200: InstanceOut, 404: ErrorOut}
)
def get_instance(request, instance_id: int):
    """获取实例详细信息"""
    instance = Instance.objects.filter(
        pk=instance_id,
        deleted_at__isnull=True,
    ).first()

    if instance is None:
        return Status(404, {
            'code': 'instance_not_found',
            'message': '数据库实例不存在',
        })

    return Status(200, instance)


@router.post(
    '/instances',
    response={201: InstanceOut, (404, 409): ErrorOut, 422: ValidationErrorOut},
)
def create_instance(request, payload: InstanceIn):
    """创建实例"""
    try:
        with transaction.atomic():
            cluster = Cluster.objects.select_for_update().filter(
                pk=payload.cluster_id,
                deleted_at__isnull=True,
            ).first()

            if cluster is None:
                return Status(404, {
                    'code': 'cluster_not_found',
                    'message': '集群不存在或已删除',
                })

            instance = Instance.objects.create(**payload.model_dump())

    except IntegrityError as exc:
        if isinstance(exc.__cause__, UniqueViolation):
            return Status(409, {
                'code': 'instance_code_or_name_conflict',
                'message': '实例编码或集群内实例名称冲突',
            })

        if isinstance(exc.__cause__, ForeignKeyViolation):
            return Status(404, {
                'code': 'cluster_not_found',
                'message': '集群不存在',
            })

        raise

    return Status(201, instance)

@router.put(
    '/instances/{instance_id}',
    response={200: InstanceOut, (404, 409): ErrorOut, 422: ValidationErrorOut},
)
def update_instance(request, instance_id: int,  payload: InstanceIn):
    """更新数据库实例"""
    try:
        with transaction.atomic():
            cluster = Cluster.objects.select_for_update().filter(
                pk=payload.cluster_id,
                deleted_at__isnull=True,
            ).first()

            if cluster is None:
                return Status(404, {
                    'code': 'cluster_not_found',
                    'message': '集群不存在或已删除',
                })

            instance = Instance.objects.select_for_update().filter(
                pk=instance_id,
                deleted_at__isnull=True,
            ).first()

            if instance is None:
                return Status(404, {
                    'code': 'instance_not_found',
                    'message': '实例不存在或已删除',
                })

            data = payload.model_dump()
            for key, value in data.items():
                setattr(instance, key, value)
            instance.save(update_fields=[*data, 'updated_at'])
    except IntegrityError as exc:
        if isinstance(exc.__cause__, UniqueViolation):
            return Status(409, {
                'code': 'instance_code_or_name_conflict',
                'message': '实例编码或集群内实例名称冲突',
            })

        if isinstance(exc.__cause__, ForeignKeyViolation):
            return Status(404, {
                'code': 'cluster_not_found',
                'message': '集群不存在',
            })

        raise

    return Status(200, instance)


@router.delete(
    '/instances/{instance_id}',
    response={204: None, 404: ErrorOut}
)
def delete_instance(request, instance_id: int):
    """删除实例"""
    with transaction.atomic():
        instance = Instance.objects.select_for_update().filter(
            pk=instance_id,
            deleted_at__isnull=True,
        ).first()

        if instance is None:
            return Status(404, {
                'code': 'instance_not_found',
                'message': '数据库实例不存在或已删除',
            })

        instance.deleted_at = timezone.now()
        instance.save(update_fields=['deleted_at', 'updated_at'])

        return Status(204, None)

@router.post(
    '/instances/{instance_id}/probe',
    response={200: ProbeOut, 404: ErrorOut},
)
def probe_instance(request, instance_id: int):
    """探测数据库实例 TCP 端口是否可达"""
    instance = Instance.objects.filter(
        pk=instance_id,
        deleted_at__isnull=True,
    ).first()

    if instance is None:
        return Status(404, {
            'code': 'instance_not_found',
            'message': '数据库实例不存在或已删除',
        })

    reachable, latency_ms, error = tcp_probe(
        instance.host,
        instance.port,
        settings.TCP_PROBE_TIMEOUT,
    )

    return Status(200, {
        'reachable': reachable,
        'latency_ms': round(latency_ms, 2),
        'error': error,
    })
