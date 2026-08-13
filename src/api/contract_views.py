from hashlib import sha256
from io import BytesIO

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.http import FileResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import cache_control
from django.views.decorators.http import condition, require_safe

from app.domain_vocabulary import render_glossary_rows
from app.helpers import build_absolute_app_url

OPENAPI_CONTRACT = (settings.BASE_DIR / "api" / "contracts" / "openapi.yaml").read_bytes()
OPENAPI_CONTRACT_ETAG = f'"{sha256(OPENAPI_CONTRACT).hexdigest()}"'


def _contract_etag(_request):
    return OPENAPI_CONTRACT_ETAG


def _api_example_url(route_name):
    path = f"{reverse(route_name).rstrip('/')}/"
    return build_absolute_app_url(None, path) or f"https://YOUR_FLOPPY_HOST{path}"


@login_not_required
@require_safe
def api_docs(request):
    """Render the public, offline API reference index."""
    return render(
        request,
        "api/docs.html",
        {
            "glossary_terms": render_glossary_rows(),
            "info_url": _api_example_url("api_info"),
            "preferences_url": _api_example_url("api_user_preferences"),
        },
    )


@login_not_required
@require_safe
@cache_control(public=True, max_age=3600)
@condition(etag_func=_contract_etag)
def openapi_contract(_request):
    """Serve the committed OpenAPI contract with public cache validation."""
    return FileResponse(BytesIO(OPENAPI_CONTRACT), content_type="application/yaml")
