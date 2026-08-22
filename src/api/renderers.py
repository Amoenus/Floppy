from rest_framework.renderers import JSONRenderer

from app.image_cache import rewrite_payload_images


class ImageCacheJSONRenderer(JSONRenderer):
    """Rewrite approved image fields at the final API representation boundary."""

    def render(self, data, accepted_media_type=None, renderer_context=None):
        """Rewrite image fields before serializing the API response to JSON."""
        request = (renderer_context or {}).get("request")
        return super().render(
            rewrite_payload_images(data, request=request),
            accepted_media_type=accepted_media_type,
            renderer_context=renderer_context,
        )
