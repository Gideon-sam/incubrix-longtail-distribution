"""
Assisted connector — Core connector for non-automatable destinations.

Builds a ready-to-post pack: media files, caption, posting link,
and a rules checklist. A human uses this pack to post manually.
"""
from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import datetime, timezone

from api.config import settings
from api.schemas.connector import (
    Rendition, DestinationRef, Connection,
    ValidateResponse, PublishResponse, GetStatusResponse,
    DeleteResponse, BuildAssistPackResponse,
)
from api.middleware.logging_mw import get_logger
from connectors.base import BaseConnector

log = get_logger("connectors.assisted")


class AssistedConnector(BaseConnector):
    """Builds a manual posting pack for destinations where automation is not allowed."""

    @property
    def key(self) -> str:
        return "assisted"

    @property
    def manifest_path(self) -> str:
        return str(__file__).replace("connector.py", "manifest.yaml")

    async def validate(
        self, rendition: Rendition, destination: DestinationRef, connection: Connection
    ) -> ValidateResponse:
        violations = []
        if not rendition.title.strip():
            violations.append({"field": "title", "message": "Title is required."})
        if not rendition.body.strip():
            violations.append({"field": "body", "message": "Body is required."})
        return ValidateResponse(ok=len(violations) == 0, violations=violations)

    async def publish(
        self,
        rendition: Rendition,
        destination: DestinationRef,
        connection: Connection,
        idempotency_key: str,
    ) -> PublishResponse:
        """Build and return the assist pack URL as the 'live URL'."""
        pack = await self.build_assist_pack(rendition, destination)
        pack_id = str(uuid.uuid4())
        log.info("assisted_pack_built", pack_id=pack_id, files=len(pack.files))
        return PublishResponse(
            platform_post_id=pack_id,
            live_url=pack.deep_link or f"https://incubrix.app/assist/{pack_id}",
            status="assisted",
        )

    async def get_status(
        self, platform_post_id: str, connection: Connection
    ) -> GetStatusResponse:
        """Assisted posts can't be checked — pack delivery is the status."""
        return GetStatusResponse(status="assisted", live_url=None)

    async def delete(
        self, platform_post_id: str, connection: Connection
    ) -> DeleteResponse:
        """Nothing to delete — the pack is a local file."""
        return DeleteResponse(deleted=True)

    async def build_assist_pack(
        self, rendition: Rendition, destination: DestinationRef
    ) -> BuildAssistPackResponse:
        """
        Build a complete ready-to-post pack as a ZIP file.
        Contents: caption.txt, post.md, checklist.txt, metadata.json
        In SIMULATION_MODE: return pack metadata without uploading to MinIO.
        """
        pack_id = str(uuid.uuid4())

        # Read rules from destination (rules field exists in DestinationRef schema)
        rules = destination.rules or {}
        cfg = destination.instance_config or {}
        self_promo_allowed = rules.get("self_promo_allowed", cfg.get("self_promo_allowed", True))
        disclosure_required = rules.get("disclosure_required", cfg.get("disclosure_required", False))

        # Build checklist from destination rules
        checklist = [
            "[ ] Read the community rules before posting",
            "[ ] Verify content is not self-promotional" if not self_promo_allowed
            else "[ ] Ensure content adds value to the community",
            "[ ] Check posting frequency — no more than allowed per window",
            "[ ] Include all required attribution",
            "[ ] Submit using the deep link provided",
        ]
        if not self_promo_allowed:
            checklist.insert(1, "[ ] ⚠ Self-promotion is NOT allowed in this community")
        if disclosure_required or rendition.is_ai_generated:
            checklist.insert(2, "[ ] ⚠ Add AI disclosure: 'This content was AI-assisted'")

        # Generate caption
        tags_str = ", ".join(rendition.tags) if rendition.tags else "None"
        caption = (
            f"📝 Ready to post to: {destination.destination_id}\n"
            f"Title: {rendition.title}\n"
            f"Tags: {tags_str}\n"
        )

        # Deep link to the destination
        deep_link: str = cfg.get("submit_url", "") or f"https://incubrix.app/assist/{pack_id}"

        # Metadata JSON
        metadata = {
            "pack_id": pack_id,
            "destination_id": destination.destination_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "title": rendition.title,
            "tags": rendition.tags,
            "is_ai_generated": rendition.is_ai_generated,
            "checklist_items": len(checklist),
        }

        # Build ZIP in memory
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("caption.txt", caption)
            zf.writestr("post.md", f"# {rendition.title}\n\n{rendition.body}")
            zf.writestr("checklist.txt", "\n".join(checklist))
            zf.writestr("metadata.json", json.dumps(metadata, indent=2))
        zip_bytes = zip_buffer.getvalue()

        pack_path = f"assist_packs/{pack_id}/pack.zip"
        pack_url: str

        if settings.SIMULATION_MODE:
            # Skip MinIO upload in simulation mode
            pack_url = f"http://localhost:9000/incubrix/{pack_path}"
            log.info("assisted_pack_sim", pack_id=pack_id, size=len(zip_bytes))
        else:
            try:
                from api.services.storage import upload_file, get_download_url
                upload_file(pack_path, zip_bytes, content_type="application/zip")
                pack_url = get_download_url(pack_path)
                log.info("assisted_pack_uploaded", pack_id=pack_id, url=pack_url)
            except Exception as e:
                log.warning("assisted_pack_storage_error", error=str(e))
                pack_url = f"local://{pack_path}"

        return BuildAssistPackResponse(
            files=[pack_url],
            caption=caption,
            deep_link=deep_link,
            checklist=checklist,
        )
