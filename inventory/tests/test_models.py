import pytest
from django.core.exceptions import ValidationError
from django.db import transaction, IntegrityError
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from inventory.models import Cluster, DatabaseInstance, Department


pytestmark = pytest.mark.django_db


@pytest.fixture
def department():
    return Department.objects.create(
        code='game-dev',
        name='游戏研发部',
    )

@pytest.fixture
def cluster(department):
    return Cluster.objects.create(
        code='player-db',
        name='玩家数据库集群',
        department=department,
        engine=Cluster.Engine.MYSQL,
        environment=Cluster.Environment.TEST,
    )

@pytest.fixture
def instance_data(cluster):
    return {
        'code': 'player-db-01',
        'name': '玩家数据库01',
        'cluster': cluster,
        'host': '192.168.2.10',
        'port': 3006,
        'role': DatabaseInstance.Role.PRIMARY,
        'status': DatabaseInstance.Status.ACTIVE,
    }


def test_create_instance(instance_data, cluster, department):
    """测试数据库实例创建与关联"""
    instance = DatabaseInstance.objects.create(**instance_data)
    instance.refresh_from_db()

    assert instance.cluster_id == cluster.pk
    assert instance.cluster.department_id == department.pk
    assert cluster.instances.filter(pk=instance.pk).exists()

@pytest.mark.parametrize('port', [-1, 0, 65536])
def test_invalid_port_validation(instance_data, port):
    """测试非法端口校验"""
    instance_data['port'] = port
    instance = DatabaseInstance(**instance_data)
    with pytest.raises(ValidationError) as exc_info:
        instance.full_clean()  # 校验数据

    assert 'port' in exc_info.value.message_dict

@pytest.mark.parametrize('port', [-1, 0, 65536])
def test_invalid_port_save(instance_data, port):
    """测试非法端口存储"""
    instance_data['port'] = port
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            DatabaseInstance.objects.create(**instance_data)

def test_department_code_duplicate(department):
    """测试部门编码重复"""
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Department.objects.create(code=department.code, name='开发部2')

def test_cluster_code_duplicate(department, cluster):
    """测试集群编码重复"""
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Cluster.objects.create(
                code=cluster.code,
                name='玩家数据库2',
                department=department,
                engine=Cluster.Engine.MYSQL,
                environment=Cluster.Environment.TEST,
            )

def test_instance_code_duplicate_with_different_cluster(department, cluster, instance_data):
    """测试数据库实例编码重复，即使属于不同集群"""
    cluster2 = Cluster.objects.create(
        code='player-db-2',
        name='玩家数据库集群2',
        department=department,
        engine=Cluster.Engine.MYSQL,
        environment=Cluster.Environment.TEST,
    )
    instance_data2 = {
        'code': instance_data['code'],
        'name': '玩家数据库02',
        'cluster': cluster2,
        'host': '192.168.2.11',
        'port': 3005,
        'role': DatabaseInstance.Role.PRIMARY,
        'status': DatabaseInstance.Status.ACTIVE,
    }
    DatabaseInstance.objects.create(**instance_data)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            DatabaseInstance.objects.create(**instance_data2)

def test_instance_name_duplicate(cluster, instance_data):
    """测试同一集群实例名称相同"""
    instance_data2 = {
        **instance_data,
        'code': 'player-db-2',
    }
    DatabaseInstance.objects.create(**instance_data)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            DatabaseInstance.objects.create(**instance_data2)

def test_cannot_delete_department_with_cluster(department, cluster):
    """测试不能删除含有集群的部门"""
    with pytest.raises(ProtectedError):
        department.delete()

    assert Department.objects.filter(pk=department.pk).exists()
    assert Cluster.objects.filter(pk=cluster.pk).exists()

def test_cannot_delete_cluster_with_instance(cluster, instance_data):
    """测试不能删除含有实例的集群"""
    instance = DatabaseInstance.objects.create(**instance_data)
    with pytest.raises(ProtectedError):
        cluster.delete()

    assert Cluster.objects.filter(pk=cluster.pk).exists()
    assert DatabaseInstance.objects.filter(pk=instance.pk).exists()

@pytest.mark.parametrize(
    'status, has_retired_at, success',
    [
        ('retired', True, True),
        ('retired', False, False),
        ('active', False, True),
        ('active', True, False),
        ('paused', False, True),
        ('paused', True, False),
    ]
)
def test_retire_status(
    instance_data,
    status,
    has_retired_at,
    success,
):
    """测试状态与退役时间是否符合预期"""
    instance_data['status'] = status
    if has_retired_at:
        instance_data['retired_at'] = timezone.now()
    else:
        instance_data['retired_at'] = None

    if success:
        instance = DatabaseInstance.objects.create(**instance_data)
        instance.refresh_from_db()

        assert instance.status == status
        assert instance.retired_at == instance_data['retired_at']
    else:
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                DatabaseInstance.objects.create(**instance_data)
