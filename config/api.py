from django.conf import settings
from ninja import NinjaAPI

from inventory.apis import router as inventory_router

api = NinjaAPI(
    title="数据库实例管理系统",
    version="1.0",
    docs_url="/docs" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
)
api.add_router("/v1", inventory_router)
