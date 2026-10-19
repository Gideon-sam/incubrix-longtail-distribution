"""
MRSS (Media RSS) connector — Advanced connector (L2 feed).

Generates an MRSS XML feed file and saves to MinIO.
No auth required — pure file generation. Feed URL is the MinIO download link.
"""
from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from api.config import settings
from api.schemas.connector import (
    Rendition, DestinationRef, Connection,
    ValidateResponse, PublishResponse, GetStatusResponse, DeleteResponse,
)
from api.middleware.logging_mw import get_logger
from connectors.base import BaseConnector

log = get_logger("connectors.mrss")
_feeds: dict[str, str] = {}  # post_id → MinIO path / local path


class MrssConnector(BaseConnector):
    """MRSS connector — generates XML feeds saved to MinIO."""

    @property
    def key(self) -> str:
        return "mrss"

    @property
    def manifest_path(self) -> str:
        return str(__file__).replace("connector.py", "manifest.yaml")

    async def validate(
        self,
        rendition: Rendition,
        destination: DestinationRef,
        connection: Connection,
    ) -> ValidateResponse:
        violations = []
        if not rendition.title.strip():
            violations.append({"field": "title", "message": "Title required."})
        if not rendition.canonical_url and not rendition.media_urls:
            violations.append({
                "field": "canonical_url",
                "message": "canonical_url or at least one media_url required for MRSS.",
            })
        return ValidateResponse(ok=len(violations) == 0, violations=violations)

    async def publish(
        self,
        rendition: Rendition,
        destination: DestinationRef,
        connection: Connection,
        idempotency_key: str,
    ) -> PublishResponse:
        post_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

        # Build MRSS XML
        rss = ET.Element("rss", {
            "version": "2.0",
            "xmlns:media": "http://search.yahoo.com/mrss/",
        })
        channel = ET.SubElement(rss, "channel")
        ET.SubElement(channel, "title").text = (
            destination.instance_config.get("feed_title", "IncuBrix Feed")
        )
        ET.SubElement(channel, "link").text = rendition.canonical_url or ""
        ET.SubElement(channel, "description").text = "IncuBrix video distribution feed"

        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = rendition.title[:200]
        ET.SubElement(item, "description").text = rendition.body[:5000]
        ET.SubElement(item, "pubDate").text = now
        ET.SubElement(item, "guid").text = post_id
        if rendition.canonical_url:
            ET.SubElement(item, "link").text = rendition.canonical_url
        for url in rendition.media_urls[:5]:
            ET.SubElement(
                item,
                "{http://search.yahoo.com/mrss/}content",
                {"url": url, "type": "video/mp4"},
            )

        xml_bytes = ET.tostring(rss, encoding="utf-8", xml_declaration=True)
        path = f"mrss/{post_id}/feed.xml"

        # Storage: use MinIO in production, in-memory in simulation
        if settings.SIMULATION_MODE:
            # Store path reference only — no MinIO call
            feed_url = f"http://localhost:9000/incubrix/{path}"
        else:
            try:
                from api.services.storage import upload_file, get_download_url
                upload_file(path, xml_bytes, "application/rss+xml")
                feed_url = get_download_url(path)
            except Exception as e:
                log.warning("mrss_storage_error", error=str(e))
                feed_url = f"local://{path}"

        _feeds[post_id] = path
        log.info("mrss_feed_generated", post_id=post_id, feed_url=feed_url)
        return PublishResponse(platform_post_id=post_id, live_url=feed_url, status="published")

    async def get_status(
        self,
        platform_post_id: str,
        connection: Connection,
    ) -> GetStatusResponse:
        path = _feeds.get(platform_post_id)
        if not path:
            return GetStatusResponse(status="deleted")
        if settings.SIMULATION_MODE:
            feed_url = f"http://localhost:9000/incubrix/{path}"
        else:
            try:
                from api.services.storage import get_download_url
                feed_url = get_download_url(path)
            except Exception:
                feed_url = f"local://{path}"
        return GetStatusResponse(status="published", live_url=feed_url)

    async def delete(
        self,
        platform_post_id: str,
        connection: Connection,
    ) -> DeleteResponse:
        _feeds.pop(platform_post_id, None)
        log.info("mrss_deleted", post_id=platform_post_id)
        return DeleteResponse(deleted=True)
