from typing import ClassVar

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Department(models.Model):
    """部门模型"""

    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} ({self.code})"


class Cluster(models.Model):
    """集群模型"""

    class Engine(models.TextChoices):
        MYSQL = "mysql"
        POSTGRES = "postgres"

    class Environment(models.TextChoices):
        DEVELOPMENT = "dev"
        TEST = "test"
        PRODUCTION = "prod"

    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=64)
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name="clusters"
    )
    engine = models.CharField(max_length=16, choices=Engine.choices)
    environment = models.CharField(max_length=16, choices=Environment.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} ({self.code})"


class DatabaseInstance(models.Model):
    """数据库实例模型"""

    class Role(models.TextChoices):
        PRIMARY = "primary"
        REPLICA = "replica"
        STANDALONE = "standalone"

    class Status(models.TextChoices):
        ACTIVE = "active"
        PAUSED = "paused"

    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=64)
    cluster = models.ForeignKey(
        Cluster, on_delete=models.PROTECT, related_name="instances"
    )
    dbname = models.CharField(max_length=63, blank=True)
    host = models.CharField(max_length=255)
    port = models.IntegerField(
        validators=[
            MinValueValidator(1),
            MaxValueValidator(65535),
        ]
    )
    role = models.CharField(max_length=16, choices=Role.choices)
    status = models.CharField(max_length=16, choices=Status.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints: ClassVar[list] = [
            models.CheckConstraint(
                condition=models.Q(port__gte=1, port__lte=65535),
                name="instance_port_valid_range",
            ),
            # 同一集群内实例名称唯一
            models.UniqueConstraint(
                fields=["cluster", "name"],
                name="unique_instance_name_per_cluster",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"


class InstanceDailySnapshot(models.Model):
    """实例数量统计模型"""

    snapshot_date = models.DateField()
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="daily_stats",
    )
    cluster = models.ForeignKey(
        Cluster,
        on_delete=models.PROTECT,
        related_name="daily_stats",
    )
    instance_count = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints: ClassVar[list] = [
            models.UniqueConstraint(
                fields=["snapshot_date", "cluster"],
                name="unique_daily_snapshot_per_cluster",
            ),
        ]

        indexes: ClassVar[list] = [
            models.Index(
                fields=["snapshot_date", "department"], name="index_date_department"
            )
        ]

    def __str__(self):
        return f"{self.snapshot_date} - {self.department}, {self.cluster}, {self.instance_count}"


class InstanceCredential(models.Model):
    """凭据模型"""

    class RotationStatus(models.TextChoices):
        IDLE = "idle"
        ROTATING = "rotating"
        FAILED = "failed"

    status = models.CharField(
        max_length=16,
        choices=RotationStatus.choices,
        default=RotationStatus.IDLE,
    )
    pending_encrypted_password = models.TextField(null=True, blank=True)
    instance = models.OneToOneField(
        DatabaseInstance,
        on_delete=models.CASCADE,
        related_name="credential",
    )
    username = models.CharField(max_length=128)
    encrypted_password = models.TextField()
    rotation_started_at = models.DateTimeField(null=True, blank=True)
    rotated_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.instance}"
