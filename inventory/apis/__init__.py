from ninja import Router

from .clusters import router as cluster_router
from .departments import router as department_router
from .instances import router as instance_router
from .credentials import router as credential_router


router = Router()
router.add_router('', cluster_router)
router.add_router('', department_router)
router.add_router('', instance_router)
router.add_router('', credential_router)
