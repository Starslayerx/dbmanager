from ninja import NinjaAPI

from inventory.apis import router as inventory_router

api = NinjaAPI(title="数据库实例管理系统", version="1.0")
api.add_router("/v1", inventory_router)
