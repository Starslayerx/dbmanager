from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator


class Department(models.Model):
    """部门模型"""
    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.name} ({self.code})'


class Cluster(models.Model):
    """集群模型"""
    class Engine(models.TextChoices):
        MYSQL = 'mysql'
        POSTGRES = 'postgres'

    class Environment(models.TextChoices):
        DEVELOPMENT = 'dev'
        TEST = 'test'
        PRODUCTION = 'prod'

    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=64)
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name='clusters')
    engine = models.CharField(max_length=16, choices=Engine.choices)
    environment = models.CharField(max_length=16, choices=Environment.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.name} ({self.code})'


class DatabaseInstance(models.Model):
    """数据库实例模型"""
    class Role(models.TextChoices):
        PRIMARY = 'primary'
        REPLICA = 'replica'
        STANDALONE = 'standalone'

    class Status(models.TextChoices):
        ACTIVE = 'active'
        PAUSED = 'paused'

    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=64)
    cluster = models.ForeignKey(Cluster, on_delete=models.PROTECT, related_name='instances')
    host = models.CharField(max_length=255)
    port = models.IntegerField(validators=[
        MinValueValidator(1),
        MaxValueValidator(65535),
    ])
    role = models.CharField(max_length=16, choices=Role.choices)
    status = models.CharField(max_length=16, choices=Status.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(port__gte=1, port__lte=65535),
                name='instance_port_valid_range',
            ),
            # 同一集群内实例名称唯一
            models.UniqueConstraint(
                fields=['cluster', 'name'],
                name='unique_instance_name_per_cluster',
            ),
        ]

    def __str__(self):
        return f'{self.name} ({self.code})'
