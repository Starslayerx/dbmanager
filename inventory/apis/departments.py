from django.db import IntegrityError, transaction
from django.utils import timezone
from ninja import Router, Status
from ninja.pagination import PageNumberPagination, paginate
from psycopg.errors import UniqueViolation

from inventory.models import Department
from inventory.schemas import DepartmentIn, DepartmentOut, ErrorOut

router = Router(tags=["部门"])


@router.get("/departments", response=list[DepartmentOut])
@paginate(PageNumberPagination, page_size=20)
def list_departments(request):
    """获取部门列表"""
    queryset = Department.objects.filter(
        deleted_at__isnull=True,
    ).order_by("id")

    return queryset


@router.get(
    "/departments/{department_id}",
    response={200: DepartmentOut, 404: ErrorOut},
)
def get_department(request, department_id: int):
    """获取部门详细信息"""
    department = Department.objects.filter(
        pk=department_id,
        deleted_at__isnull=True,
    ).first()

    if department is None:
        return Status(
            404,
            {
                "code": "department_not_found",
                "message": "部门不存在",
            },
        )

    return Status(200, department)


@router.post(
    "/departments",
    response={201: DepartmentOut, 409: ErrorOut},
)
def create_department(request, payload: DepartmentIn):
    """创建部门"""
    try:
        with transaction.atomic():
            department = Department.objects.create(**payload.model_dump())
    except IntegrityError as exc:
        if isinstance(exc.__cause__, UniqueViolation):
            return Status(
                409,
                {
                    "code": "department_code_conflict",
                    "message": "部门编码已存在",
                },
            )
        raise

    return Status(201, department)


@router.put(
    "/departments/{department_id}",
    response={200: DepartmentOut, (404, 409): ErrorOut},
)
def update_department(request, department_id: int, payload: DepartmentIn):
    """更新部门"""
    try:
        with transaction.atomic():
            department = (
                Department.objects.select_for_update()
                .filter(
                    pk=department_id,
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

            data = payload.model_dump()
            for key, value in data.items():
                setattr(department, key, value)
            department.save(update_fields=[*data, "updated_at"])
    except IntegrityError as exc:
        if isinstance(exc.__cause__, UniqueViolation):
            return Status(
                409,
                {
                    "code": "department_code_conflict",
                    "message": "部门编码已存在",
                },
            )
        raise

    return Status(200, department)


@router.delete(
    "/departments/{department_id}",
    response={204: None, (404, 409): ErrorOut},
)
def delete_department(request, department_id: int):
    """删除部门"""
    with transaction.atomic():
        department = (
            Department.objects.select_for_update()
            .filter(
                pk=department_id,
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

        if department.clusters.filter(deleted_at__isnull=True).exists():
            return Status(
                409,
                {
                    "code": "department_has_clusters",
                    "message": "部门存在未删除的集群，不能删除",
                },
            )

        department.deleted_at = timezone.now()
        department.save(update_fields=["deleted_at", "updated_at"])

        return Status(204, None)
