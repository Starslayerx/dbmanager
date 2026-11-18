from datetime import datetime
from typing import Annotated, Any
from ninja import Schema
from pydantic import Field, StringConstraints

from inventory.models import Cluster, DatabaseInstance, InstanceCredential


CodeText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r'^[a-z0-9][a-z0-9_-]*$',
    )
]

NameText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
    )
]

DBNameText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        max_length=63,
        pattern=r'^(?:[A-Za-z_][A-Za-z0-9_]*)?$',
    )
]

class DepartmentIn(Schema):
    code: CodeText
    name: NameText

class DepartmentOut(Schema):
    id: int
    code: str
    name: str
    created_at: datetime
    updated_at: datetime

class ClusterIn(Schema):
    code: CodeText
    name: NameText
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
    code: CodeText
    name: NameText
    cluster_id: Annotated[int, Field(gt=0)]
    dbname: DBNameText = ''
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
    dbname: str
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

class ProbeOut(Schema):
    reachable: bool
    latency_ms: float
    error: str | None

class CredentialIn(Schema):
    username: Annotated[str, StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
    )]
    password: Annotated[str, Field(min_length=8, max_length=128)]

class CredentialOut(Schema):
    username: str
    status: InstanceCredential.RotationStatus
    rotated_at: datetime
    created_at: datetime
    updated_at: datetime
