from hashlib import sha256
from io import BytesIO

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.http import FileResponse
from django.shortcuts import render
from django.views.decorators.cache import cache_control
from django.views.decorators.http import condition, require_GET, require_safe

from app.domain_vocabulary import render_glossary_rows

OPENAPI_CONTRACT = (settings.BASE_DIR / "api" / "contracts" / "openapi.yaml").read_bytes()
OPENAPI_CONTRACT_ETAG = f'"{sha256(OPENAPI_CONTRACT).hexdigest()}"'


def _contract_etag(_request):
    return OPENAPI_CONTRACT_ETAG


@login_not_required
@require_GET
def api_docs(request):
    """Render the public, offline API reference index."""
    return render(
        request,
        "api/docs.html",
        {"glossary_terms": render_glossary_rows()},
    )


@login_not_required
@require_safe
@cache_control(public=True, max_age=3600)
@condition(etag_func=_contract_etag)
def openapi_contract(_request):
    """Serve the committed OpenAPI contract with public cache validation."""
    return FileResponse(BytesIO(OPENAPI_CONTRACT), content_type="application/yaml")
