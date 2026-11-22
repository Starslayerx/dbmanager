import pytest
from django.utils import timezone

from config.api import api
from inventory.models import Cluster, DatabaseInstance, Department
from inventory.schemas import ValidationErrorOut

pytestmark = pytest.mark.django_db
MODELS = {
    "departments": Department,
    "clusters": Cluster,
    "instances": DatabaseInstance,
}


@pytest.fixture
def payloads(settings):
    settings.ALLOWED_HOSTS = ["testserver"]
    department = Department.objects.create(code="parent-department", name="所属部门")
    cluster = Cluster.objects.create(
        code="parent-cluster",
        name="所属集群",
        department=department,
        engine="mysql",
        environment="test",
    )
    return {
        "departments": {"code": "department", "name": "部门"},
        "clusters": {
            "code": "cluster",
            "name": "集群",
            "department_id": department.pk,
            "engine": "mysql",
            "environment": "test",
        },
        "instances": {
            "code": "instance",
            "name": "实例",
            "cluster_id": cluster.pk,
            "host": "localhost",
            "port": 3306,
            "role": "primary",
            "status": "active",
        },
    }


@pytest.mark.parametrize("resource", MODELS)
def test_crud_responses(client, payloads, resource):
    url = f"/api/v1/{resource}"
    payload = payloads[resource]
    response = client.post(url, data=payload, content_type="application/json")
    assert response.status_code == 201
    pk = response.json()["id"]
    detail_url = f"{url}/{pk}"
    assert client.get(detail_url).status_code == 200
    assert any(item["id"] == pk for item in client.get(url).json()["items"])
    assert (
        client.post(url, data=payload, content_type="application/json").status_code
        == 409
    )

    other = dict(payload, code="other", name="另一条记录")
    other_pk = MODELS[resource].objects.create(**other).pk
    response = client.put(
        f"{url}/{other_pk}", data=payload, content_type="application/json"
    )
    assert response.status_code == 409
    assert MODELS[resource].objects.get(pk=other_pk).code == "other"

    updated = dict(payload, name="更新后的名称")
    response = client.put(detail_url, data=updated, content_type="application/json")
    assert response.status_code == 200
    assert response.json()["name"] == updated["name"]
    assert client.delete(detail_url).status_code == 204
    assert MODELS[resource].objects.get(pk=pk).deleted_at is not None
    assert client.get(detail_url).status_code == 404
    assert (
        client.put(
            detail_url, data=updated, content_type="application/json"
        ).status_code
        == 404
    )
    assert client.delete(detail_url).status_code == 404
    assert not any(item["id"] == pk for item in client.get(url).json()["items"])


@pytest.mark.parametrize("resource", ["departments", "clusters"])
def test_delete_parent_with_child(client, payloads, resource):
    if resource == "departments":
        pk = payloads["clusters"]["department_id"]
        child = Cluster.objects.get(pk=payloads["instances"]["cluster_id"])
    else:
        pk = payloads["instances"]["cluster_id"]
        child = DatabaseInstance.objects.create(**payloads["instances"])

    url = f"/api/v1/{resource}/{pk}"
    assert client.delete(url).status_code == 409
    child.deleted_at = timezone.now()
    child.save(update_fields=["deleted_at"])
    assert client.delete(url).status_code == 204


@pytest.mark.parametrize("method", ["post", "put"])
@pytest.mark.parametrize("deleted", [False, True])
def test_instance_rejects_invalid_cluster(client, payloads, method, deleted):
    payload = payloads["instances"].copy()
    url = "/api/v1/instances"
    if method == "put":
        url += f"/{DatabaseInstance.objects.create(**payload).pk}"
    if deleted:
        Cluster.objects.filter(pk=payload["cluster_id"]).update(
            deleted_at=timezone.now()
        )
    else:
        payload["cluster_id"] += 100000
    response = getattr(client, method)(
        url, data=payload, content_type="application/json"
    )
    assert response.status_code == 404
    assert response.json()["code"] == "cluster_not_found"


@pytest.mark.parametrize("method", ["post", "put"])
@pytest.mark.parametrize("port", [0, 65536])
def test_instance_validation_response(client, payloads, method, port):
    payload = dict(payloads["instances"], port=port)
    url = "/api/v1/instances"
    if method == "put":
        url += f"/{DatabaseInstance.objects.create(**payloads['instances']).pk}"
    response = getattr(client, method)(
        url, data=payload, content_type="application/json"
    )
    assert response.status_code == 422
    assert ValidationErrorOut.model_validate(response.json()).detail


@pytest.mark.parametrize(
    "path, method",
    [
        ("/api/v1/instances", "post"),
        ("/api/v1/instances/{instance_id}", "put"),
    ],
)
def test_instance_validation_schema(path, method):
    schema = api.get_openapi_schema()
    response = schema["paths"][path][method]["responses"][422]
    assert response["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ValidationErrorOut"
    )
