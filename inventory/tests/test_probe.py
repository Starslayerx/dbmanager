import socket

import pytest
from django.utils import timezone

from inventory.models import Cluster, DatabaseInstance, Department


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def allowed_hosts(settings):
    settings.ALLOWED_HOSTS = ['testserver']


@pytest.fixture
def instance():
    department = Department.objects.create(code='probe-department', name='探测部门')
    cluster = Cluster.objects.create(
        code='probe-cluster',
        name='探测集群',
        department=department,
        engine=Cluster.Engine.MYSQL,
        environment=Cluster.Environment.TEST,
    )
    return DatabaseInstance.objects.create(
        code='probe-instance',
        name='探测实例',
        cluster=cluster,
        host='127.0.0.1',
        port=3306,
        role=DatabaseInstance.Role.PRIMARY,
        status=DatabaseInstance.Status.ACTIVE,
    )


@pytest.fixture
def listening_port():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(('127.0.0.1', 0))
    server.listen()
    try:
        yield server.getsockname()[1]
    finally:
        server.close()


@pytest.fixture
def closed_port():
    # 占用端口但不监听，连接会被拒绝，同时端口不会被其他进程复用。
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(('127.0.0.1', 0))
    try:
        yield server.getsockname()[1]
    finally:
        server.close()


def probe(client, instance):
    return client.post(f'/api/v1/instances/{instance.pk}/probe')


def test_probe_reachable(client, instance, listening_port):
    instance.port = listening_port
    instance.save(update_fields=['port'])

    response = probe(client, instance)

    assert response.status_code == 200
    body = response.json()
    assert body['reachable'] is True
    assert body['latency_ms'] >= 0
    assert body['error'] is None


def test_probe_unreachable(client, instance, closed_port):
    instance.port = closed_port
    instance.save(update_fields=['port'])

    response = probe(client, instance)

    assert response.status_code == 200
    body = response.json()
    assert body['reachable'] is False
    assert body['error']


def test_probe_instance_not_found(client):
    response = client.post('/api/v1/instances/999999/probe')

    assert response.status_code == 404
    assert response.json()['code'] == 'instance_not_found'


def test_probe_deleted_instance(client, instance, listening_port):
    instance.port = listening_port
    instance.deleted_at = timezone.now()
    instance.save(update_fields=['port', 'deleted_at'])

    response = probe(client, instance)

    assert response.status_code == 404
    assert response.json()['code'] == 'instance_not_found'
