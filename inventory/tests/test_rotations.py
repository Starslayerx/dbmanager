from datetime import timedelta

import pytest
from django.utils import timezone

from inventory.models import (
    Cluster,
    DatabaseInstance,
    Department,
    InstanceCredential,
)
from inventory.services.crypto import decrypt_password, encrypt_password
from inventory.services.rotations import (
    claim_rotation,
    execute_rotation,
    finalize_rotation,
    recover_stale_rotations,
)


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def allowed_hosts(settings):
    settings.ALLOWED_HOSTS = ['testserver']


@pytest.fixture
def instance():
    department = Department.objects.create(code='rotation-dept', name='轮换部门')
    cluster = Cluster.objects.create(
        code='rotation-cluster',
        name='轮换集群',
        department=department,
        engine=Cluster.Engine.POSTGRES,
        environment=Cluster.Environment.TEST,
    )
    return DatabaseInstance.objects.create(
        code='rotation-instance',
        name='轮换实例',
        cluster=cluster,
        dbname='appdb',
        host='127.0.0.1',
        port=5432,
        role=DatabaseInstance.Role.PRIMARY,
        status=DatabaseInstance.Status.ACTIVE,
    )


@pytest.fixture
def credential(instance):
    return InstanceCredential.objects.create(
        instance=instance,
        username='app',
        encrypted_password=encrypt_password('old-password'),
        rotated_at=timezone.now() - timedelta(days=1),
    )


def test_claim_and_finalize(credential):
    claimed = claim_rotation(credential.pk, 'new-password')

    assert claimed is not None
    credential.refresh_from_db()
    assert credential.status == InstanceCredential.RotationStatus.ROTATING
    assert credential.pending_encrypted_password
    assert claim_rotation(credential.pk) is None

    assert finalize_rotation(credential.pk) is True
    credential.refresh_from_db()
    assert credential.status == InstanceCredential.RotationStatus.IDLE
    assert credential.pending_encrypted_password is None
    assert decrypt_password(credential.encrypted_password) == 'new-password'


def test_execute_success(credential, monkeypatch):
    calls = []
    monkeypatch.setattr(
        'inventory.services.rotations.change_database_password',
        lambda **kwargs: calls.append(kwargs),
    )

    assert execute_rotation(credential.pk, 'new-password') is True

    assert calls[0]['old_password'] == 'old-password'
    assert calls[0]['new_password'] == 'new-password'
    credential.refresh_from_db()
    assert decrypt_password(credential.encrypted_password) == 'new-password'


def test_execute_failure_keeps_rotating_for_recovery(credential, monkeypatch):
    old_cipher = credential.encrypted_password

    def fail(**kwargs):
        raise RuntimeError('target down')

    monkeypatch.setattr(
        'inventory.services.rotations.change_database_password',
        fail,
    )

    with pytest.raises(RuntimeError):
        execute_rotation(credential.pk, 'new-password')

    credential.refresh_from_db()
    assert credential.status == InstanceCredential.RotationStatus.ROTATING
    assert credential.encrypted_password == old_cipher
    assert credential.pending_encrypted_password


def test_recover_pending_finalizes(credential, monkeypatch):
    claim_rotation(credential.pk, 'new-password')
    credential.refresh_from_db()
    credential.rotation_started_at = timezone.now() - timedelta(hours=1)
    credential.save(update_fields=['rotation_started_at'])

    monkeypatch.setattr(
        'inventory.services.rotations.verify_database_password',
        lambda **kwargs: kwargs['password'] == 'new-password',
    )

    assert recover_stale_rotations() == 1
    credential.refresh_from_db()
    assert credential.status == InstanceCredential.RotationStatus.IDLE
    assert decrypt_password(credential.encrypted_password) == 'new-password'


def test_recover_old_resets(credential, monkeypatch):
    claim_rotation(credential.pk, 'new-password')
    credential.refresh_from_db()
    credential.rotation_started_at = timezone.now() - timedelta(hours=1)
    credential.save(update_fields=['rotation_started_at'])

    monkeypatch.setattr(
        'inventory.services.rotations.verify_database_password',
        lambda **kwargs: kwargs['password'] == 'old-password',
    )

    assert recover_stale_rotations() == 1
    credential.refresh_from_db()
    assert credential.status == InstanceCredential.RotationStatus.IDLE
    assert credential.pending_encrypted_password is None
    assert decrypt_password(credential.encrypted_password) == 'old-password'


def test_api_create_and_rotate(client, instance, monkeypatch):
    url = f'/api/v1/instances/{instance.pk}/credential'
    payload = {'username': 'app', 'password': 'old-password'}

    response = client.put(
        url,
        data=payload,
        content_type='application/json',
    )
    assert response.status_code == 201

    calls = []
    monkeypatch.setattr(
        'inventory.services.rotations.change_database_password',
        lambda **kwargs: calls.append(kwargs),
    )

    payload['password'] = 'new-password'
    response = client.put(
        url,
        data=payload,
        content_type='application/json',
    )

    assert response.status_code == 200
    assert calls[0]['new_password'] == 'new-password'
    assert client.get(url).json()['status'] == 'idle'


def test_api_rejects_rotating(client, instance, credential):
    claim_rotation(credential.pk, 'new-password')
    url = f'/api/v1/instances/{instance.pk}/credential'

    response = client.put(
        url,
        data={'username': 'app', 'password': 'another-password'},
        content_type='application/json',
    )

    assert response.status_code == 409
    assert response.json()['code'] == 'credential_rotating'
