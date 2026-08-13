from hashlib import sha256
from io import BytesIO

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.http import FileResponse
from django.views.decorators.cache import cache_control
from django.views.decorators.http import condition, require_GET

OPENAPI_CONTRACT = (settings.BASE_DIR / "api" / "contracts" / "openapi.yaml").read_bytes()
OPENAPI_CONTRACT_ETAG = f'"{sha256(OPENAPI_CONTRACT).hexdigest()}"'


def _contract_etag(_request):
    return OPENAPI_CONTRACT_ETAG


@login_not_required
@require_GET
@cache_control(public=True, max_age=3600)
@condition(etag_func=_contract_etag)
def openapi_contract(_request):
    """Serve the committed OpenAPI contract with public cache validation."""
    return FileResponse(BytesIO(OPENAPI_CONTRACT), content_type="application/yaml")
