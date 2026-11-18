from django.db import IntegrityError, transaction
from django.utils import timezone
from ninja import Router, Status
from ninja.pagination import PageNumberPagination, paginate
from psycopg.errors import ForeignKeyViolation, UniqueViolation

from inventory.models import Cluster, Department
from inventory.schemas import ClusterIn, ClusterOut, ErrorOut

router = Router(tags=["集群"])


@router.get("/clusters", response=list[ClusterOut])
@paginate(PageNumberPagination, page_size=20)
def list_clusters(request, department_id: int | None = None):
    """获取集群列表"""
    queryset = Cluster.objects.filter(
        deleted_at__isnull=True,
    ).order_by("id")
    if department_id is not None:
        queryset = queryset.filter(department_id=department_id)

    return queryset


@router.get(
    "/clusters/{cluster_id}",
    response={200: ClusterOut, 404: ErrorOut},
)
def get_cluster(request, cluster_id: int):
    """获取集群详细信息"""
    cluster = Cluster.objects.filter(
        pk=cluster_id,
        deleted_at__isnull=True,
    ).first()
    if cluster is None:
        return Status(
            404,
            {
                "code": "cluster_not_found",
                "message": "集群不存在",
            },
        )

    return Status(200, cluster)


@router.post(
    "/clusters",
    response={201: ClusterOut, (404, 409): ErrorOut},
)
def create_cluster(request, payload: ClusterIn):
    """创建集群"""
    try:
        with transaction.atomic():
            department = (
                Department.objects.select_for_update()
                .filter(
                    pk=payload.department_id,
                    deleted_at__isnull=True,
                )
                .first()
            )

            if department is None:
                return Status(
                    404,
                    {
                        "code": "department_not_found",
                        "message": "部门不存在或已删除",
                    },
                )

            cluster = Cluster.objects.create(**payload.model_dump())

    except IntegrityError as exc:
        if isinstance(exc.__cause__, UniqueViolation):
            return Status(
                409,
                {
                    "code": "cluster_code_conflict",
                    "message": "集群编码已存在",
                },
            )

        if isinstance(exc.__cause__, ForeignKeyViolation):
            return Status(
                404,
                {
                    "code": "department_not_found",
                    "message": "部门不存在",
                },
            )

        raise

    return Status(201, cluster)


@router.put(
    "/clusters/{cluster_id}",
    response={200: ClusterOut, (404, 409): ErrorOut},
)
def update_cluster(request, cluster_id: int, payload: ClusterIn):
    """更新集群"""
    try:
        with transaction.atomic():
            department = (
                Department.objects.select_for_update()
                .filter(
                    pk=payload.department_id,
                    deleted_at__isnull=True,
                )
                .first()
            )

            if department is None:
                return Status(
                    404,
                    {
                        "code": "department_not_found",
                        "message": "部门不存在或已删除",
                    },
                )

            cluster = (
                Cluster.objects.select_for_update()
                .filter(
                    pk=cluster_id,
                    deleted_at__isnull=True,
                )
                .first()
            )

            if cluster is None:
                return Status(
                    404,
                    {
                        "code": "cluster_not_found",
                        "message": "集群不存在或已删除",
                    },
                )

            data = payload.model_dump()
            for key, value in data.items():
                setattr(cluster, key, value)
            cluster.save(update_fields=[*data, "updated_at"])
    except IntegrityError as exc:
        if isinstance(exc.__cause__, UniqueViolation):
            return Status(
                409,
                {
                    "code": "cluster_code_conflict",
                    "message": "集群编码已存在",
                },
            )
        if isinstance(exc.__cause__, ForeignKeyViolation):
            return Status(
                404,
                {
                    "code": "department_not_found",
                    "message": "部门不存在",
                },
            )

        raise

    return Status(200, cluster)


@router.delete(
    "/clusters/{cluster_id}",
    response={204: None, (404, 409): ErrorOut},
)
def delete_cluster(request, cluster_id: int):
    """删除集群"""
    with transaction.atomic():
        cluster = (
            Cluster.objects.select_for_update()
            .filter(
                pk=cluster_id,
                deleted_at__isnull=True,
            )
            .first()
        )

        if cluster is None:
            return Status(
                404,
                {
                    "code": "cluster_not_found",
                    "message": "集群不存在或已删除",
                },
            )

        if cluster.instances.filter(deleted_at__isnull=True).exists():
            return Status(
                409,
                {
                    "code": "cluster_has_instances",
                    "message": "集群存在未删除的实例，不能删除",
                },
            )

        cluster.deleted_at = timezone.now()
        cluster.save(update_fields=["deleted_at", "updated_at"])

        return Status(204, None)
