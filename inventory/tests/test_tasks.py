from datetime import date

import pytest
from django.utils import timezone

from inventory.models import (
    Cluster,
    DatabaseInstance,
    Department,
    InstanceDailySnapshot,
)
from inventory.tasks import collect_daily_instance_stats


pytestmark = pytest.mark.django_db

SNAPSHOT_DATE = date(2026, 11, 18)


@pytest.fixture
def department():
    return Department.objects.create(code='stats-department', name='统计部门')


@pytest.fixture
def cluster(department):
    return Cluster.objects.create(
        code='stats-cluster',
        name='统计集群',
        department=department,
        engine=Cluster.Engine.MYSQL,
        environment=Cluster.Environment.TEST,
    )


def create_instance(cluster, code, deleted=False):
    return DatabaseInstance.objects.create(
        code=code,
        name=code,
        cluster=cluster,
        host='127.0.0.1',
        port=3306,
        role=DatabaseInstance.Role.PRIMARY,
        status=DatabaseInstance.Status.ACTIVE,
        deleted_at=timezone.now() if deleted else None,
    )


def test_collect_daily_instance_stats_counts_active_instances(department, cluster):
    create_instance(cluster, 'active-1')
    create_instance(cluster, 'active-2')
    create_instance(cluster, 'deleted-instance', deleted=True)

    empty_cluster = Cluster.objects.create(
        code='empty-cluster',
        name='空集群',
        department=department,
        engine=Cluster.Engine.MYSQL,
        environment=Cluster.Environment.TEST,
    )
    deleted_cluster = Cluster.objects.create(
        code='deleted-cluster',
        name='已删除集群',
        department=department,
        engine=Cluster.Engine.MYSQL,
        environment=Cluster.Environment.TEST,
        deleted_at=timezone.now(),
    )
    create_instance(deleted_cluster, 'deleted-cluster-instance')

    created = collect_daily_instance_stats(snapshot_date=SNAPSHOT_DATE)

    assert created == 2
    snapshots = {
        snapshot.cluster_id: snapshot
        for snapshot in InstanceDailySnapshot.objects.filter(
            snapshot_date=SNAPSHOT_DATE,
        )
    }
    assert set(snapshots) == {cluster.pk, empty_cluster.pk}
    assert snapshots[cluster.pk].instance_count == 2
    assert snapshots[cluster.pk].department_id == department.pk
    assert snapshots[empty_cluster.pk].instance_count == 0
    assert not InstanceDailySnapshot.objects.filter(
        cluster=deleted_cluster,
    ).exists()


def test_collect_daily_instance_stats_is_idempotent(cluster):
    create_instance(cluster, 'first-instance')

    assert collect_daily_instance_stats(snapshot_date=SNAPSHOT_DATE) == 1
    snapshot = InstanceDailySnapshot.objects.get(
        snapshot_date=SNAPSHOT_DATE,
        cluster=cluster,
    )
    original_pk = snapshot.pk

    create_instance(cluster, 'second-instance')
    assert collect_daily_instance_stats(snapshot_date=SNAPSHOT_DATE) == 1

    snapshots = InstanceDailySnapshot.objects.filter(
        snapshot_date=SNAPSHOT_DATE,
        cluster=cluster,
    )
    assert snapshots.count() == 1
    snapshot = snapshots.get()
    assert snapshot.pk == original_pk
    assert snapshot.instance_count == 2


def test_default_snapshot_date_is_yesterday(monkeypatch, cluster):
    create_instance(cluster, 'instance')

    monkeypatch.setattr(
        'inventory.tasks.timezone.localdate',
        lambda: date(2026, 11, 19),
    )

    collect_daily_instance_stats()

    snapshot = InstanceDailySnapshot.objects.get(cluster=cluster)
    assert snapshot.snapshot_date == date(2026, 11, 18)


def test_snapshot_str_uses_instance_count(department, cluster):
    create_instance(cluster, 'instance')
    collect_daily_instance_stats(snapshot_date=SNAPSHOT_DATE)

    snapshot = InstanceDailySnapshot.objects.get(cluster=cluster)

    assert str(snapshot) == f'{SNAPSHOT_DATE} - {department}, {cluster}, 1'
