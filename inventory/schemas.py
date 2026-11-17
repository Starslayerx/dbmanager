from datetime import datetime
from typing import Annotated, Any
from ninja import Schema
from pydantic import Field, StringConstraints

from inventory.models import Cluster, DatabaseInstance


ResourceText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
    )
]

class DepartmentIn(Schema):
    code: ResourceText
    name: ResourceText

class DepartmentOut(Schema):
    id: int
    code: str
    name: str
    created_at: datetime
    updated_at: datetime

class ClusterIn(Schema):
    code: ResourceText
    name: ResourceText
    department_id: Annotated[int, Field(gt=0)]
    engine: Cluster.Engine
    environment: Cluster.Environment

class ClusterOut(Schema):
    id: int
    code: str
    name: str
    department_id: Annotated[int, Field(gt=0)]
    engine: Cluster.Engine
    environment: Cluster.Environment
    created_at: datetime
    updated_at: datetime

class InstanceIn(Schema):
    code: ResourceText
    name: ResourceText
    cluster_id: Annotated[int, Field(gt=0)]
    host: Annotated[str, StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=255,
    )]
    port: Annotated[int, Field(ge=1, le=65535)]
    role: DatabaseInstance.Role
    status: DatabaseInstance.Status

class InstanceOut(Schema):
    id: int
    code: str
    name: str
    cluster_id: int
    host: str
    port: int
    role: DatabaseInstance.Role
    status: DatabaseInstance.Status
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None

class ErrorOut(Schema):
    code: str
    message: str


class ValidationErrorOut(Schema):
    detail: list[dict[str, Any]]
