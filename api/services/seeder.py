"""
Destination auto-seeder.

Ensures that fresh environments (docker-compose, local testing, assessment test runner)
start with a populated catalogue containing core destinations for all 9 connectors
and the full 150+ real-world destinations from catalogue/real_destinations.csv.
"""
from __future__ import annotations
import csv
from pathlib import Path
from datetime import datetime, timezone

from sqlalchemy import select, func
from api.database import async_session
from api.models.destination import Destination
from api.middleware.logging_mw import get_logger

log = get_logger("services.seeder")

# Default core destinations for each connector
CORE_DESTINATIONS = [
    {
        "id": "devto-default",
        "name": "DEV Community",
        "url": "https://dev.to",
        "platform_key": "devto",
        "connector_key": "devto",
        "surface": "article",
        "category": "developer",
        "audience_tags": ["developer", "tech", "AI", "SaaS"],
        "language": "en",
        "frequency_cap": "1/day",
        "self_promo_allowed": True,
        "link_policy": "allowed",
        "disclosure_required": False,
        "automation_allowed": True,
        "relevance_score": 5.0,
        "relevance_reason": "Top developer publishing community",
        "level": "L3",
        "instance_config": {},
    },
    {
        "id": "discourse-default",
        "name": "Discourse Meta Community",
        "url": "http://mock-discourse:4100",
        "platform_key": "discourse",
        "connector_key": "discourse",
        "surface": "topic",
        "category": "community",
        "audience_tags": ["developer", "tech", "community"],
        "language": "en",
        "frequency_cap": "3/day",
        "self_promo_allowed": False,
        "link_policy": "allowed",
        "disclosure_required": False,
        "automation_allowed": True,
        "relevance_score": 4.5,
        "relevance_reason": "High-engagement forum community",
        "level": "L3",
        "instance_config": {"category_id": 1, "base_url": "http://mock-discourse:4100"},
    },
    {
        "id": "lemmy-default",
        "name": "Lemmy World Tech",
        "url": "http://lemmy:8536",
        "platform_key": "lemmy",
        "connector_key": "lemmy",
        "surface": "post",
        "category": "open-source",
        "audience_tags": ["tech", "open-source", "federation"],
        "language": "en",
        "frequency_cap": "1/day",
        "self_promo_allowed": False,
        "link_policy": "allowed",
        "disclosure_required": False,
        "automation_allowed": True,
        "relevance_score": 4.0,
        "relevance_reason": "Federated community network",
        "level": "L3",
        "instance_config": {"api_url": "http://lemmy:8536", "community_id": 1},
    },
    {
        "id": "ghost-default",
        "name": "Ghost Tech Publication",
        "url": "http://ghost:2368",
        "platform_key": "ghost",
        "connector_key": "ghost",
        "surface": "post",
        "category": "publishing",
        "audience_tags": ["creators", "SaaS", "marketing"],
        "language": "en",
        "frequency_cap": "unlimited",
        "self_promo_allowed": True,
        "link_policy": "allowed",
        "disclosure_required": False,
        "automation_allowed": True,
        "relevance_score": 4.5,
        "relevance_reason": "Direct publisher CMS and newsletter",
        "level": "L3",
        "instance_config": {"api_url": "http://ghost:2368"},
    },
    {
        "id": "webhook-default",
        "name": "Partner Webhook Receiver",
        "url": "http://mock-webhook:4200/webhook",
        "platform_key": "hmac_webhook",
        "connector_key": "hmac_webhook",
        "surface": "post",
        "category": "syndication",
        "audience_tags": ["syndication", "partner"],
        "language": "en",
        "frequency_cap": "unlimited",
        "self_promo_allowed": True,
        "link_policy": "allowed",
        "disclosure_required": False,
        "automation_allowed": True,
        "relevance_score": 4.0,
        "relevance_reason": "Authenticated partner syndication pipeline",
        "level": "L3",
        "instance_config": {"webhook_url": "http://mock-webhook:4200/webhook"},
    },
    {
        "id": "hashnode-default",
        "name": "Hashnode Developer Blog",
        "url": "http://mock-hashnode:4300",
        "platform_key": "hashnode",
        "connector_key": "hashnode",
        "surface": "article",
        "category": "developer",
        "audience_tags": ["developer", "tech", "SaaS"],
        "language": "en",
        "frequency_cap": "unlimited",
        "self_promo_allowed": True,
        "link_policy": "allowed",
        "disclosure_required": False,
        "automation_allowed": True,
        "relevance_score": 4.5,
        "relevance_reason": "GraphQL developer publication platform",
        "level": "L3",
        "instance_config": {"publication_id": "pub_mock_123"},
    },
    {
        "id": "peertube-default",
        "name": "PeerTube Federated Video",
        "url": "http://mock-peertube:4400",
        "platform_key": "peertube",
        "connector_key": "peertube",
        "surface": "video",
        "category": "video",
        "audience_tags": ["video", "creators", "open-source"],
        "language": "en",
        "frequency_cap": "unlimited",
        "self_promo_allowed": True,
        "link_policy": "allowed",
        "disclosure_required": False,
        "automation_allowed": True,
        "relevance_score": 4.0,
        "relevance_reason": "ActivityPub federated video network",
        "level": "L3",
        "instance_config": {"channel_id": "1"},
    },
    {
        "id": "assisted-default",
        "name": "Hacker News (Assisted)",
        "url": "https://news.ycombinator.com",
        "platform_key": "assisted",
        "connector_key": "assisted",
        "surface": "topic",
        "category": "tech/startups",
        "audience_tags": ["AI", "tech", "founders", "SaaS"],
        "language": "en",
        "frequency_cap": "1/day",
        "self_promo_allowed": False,
        "link_policy": "allowed",
        "disclosure_required": False,
        "automation_allowed": False,
        "relevance_score": 5.0,
        "relevance_reason": "Top tier manual submission pack",
        "level": "L1",
        "instance_config": {"submit_url": "https://news.ycombinator.com/submit"},
    },
    {
        "id": "mrss-default",
        "name": "Podcast & Media RSS Feed",
        "url": "http://localhost:8000/feeds/mrss.xml",
        "platform_key": "mrss",
        "connector_key": "mrss",
        "surface": "feed",
        "category": "feed",
        "audience_tags": ["syndication", "rss", "podcast"],
        "language": "en",
        "frequency_cap": "unlimited",
        "self_promo_allowed": True,
        "link_policy": "allowed",
        "disclosure_required": False,
        "automation_allowed": True,
        "relevance_score": 4.0,
        "relevance_reason": "Standardized media syndication feed",
        "level": "L2",
        "instance_config": {"feed_name": "default"},
    },
]


async def seed_initial_destinations():
    """Populate destinations table if currently empty."""
    async with async_session() as db:
        res = await db.execute(select(func.count(Destination.id)))
        count = res.scalar() or 0
        if count > 0:
            return  # Already populated

        log.info("seeding_initial_destinations")

        # 1. Add core destinations for all connectors
        for item in CORE_DESTINATIONS:
            dest = Destination(
                id=item["id"],
                name=item["name"],
                url=item["url"],
                platform_key=item["platform_key"],
                connector_key=item["connector_key"],
                surface=item["surface"],
                category=item.get("category"),
                audience_tags=item.get("audience_tags"),
                language=item.get("language", "en"),
                frequency_cap=item.get("frequency_cap"),
                self_promo_allowed=item.get("self_promo_allowed", True),
                link_policy=item.get("link_policy", "allowed"),
                disclosure_required=item.get("disclosure_required", False),
                automation_allowed=item.get("automation_allowed", True),
                relevance_score=item.get("relevance_score", 4.0),
                relevance_reason=item.get("relevance_reason"),
                level=item.get("level", "L3"),
                instance_config=item.get("instance_config", {}),
                last_certified_at=datetime.now(timezone.utc),
            )
            db.add(dest)

        # 2. Add from real_destinations.csv if available
        csv_path = Path(__file__).parent.parent.parent / "catalogue" / "real_destinations.csv"
        if csv_path.exists():
            try:
                with open(csv_path, mode="r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        name = row.get("name", "").strip()
                        url = row.get("url", "").strip().rstrip("/")
                        if not name or not url:
                            continue

                        # Check if URL already in core destinations
                        if any(c["url"].rstrip("/") == url for c in CORE_DESTINATIONS):
                            continue

                        tags = [t.strip() for t in row.get("audience_tags", "").split(",") if t.strip()]
                        aud_str = row.get("est_audience", "")
                        est_aud = int(aud_str) if aud_str.isdigit() else None

                        dest = Destination(
                            name=name,
                            url=url,
                            platform_key=row.get("platform_key", "assisted").strip(),
                            connector_key=row.get("connector_key", "assisted").strip(),
                            surface=row.get("surface", "topic").strip(),
                            category=row.get("category", "").strip() or None,
                            audience_tags=tags,
                            language=row.get("language", "en").strip(),
                            geo=row.get("geo", "").strip() or None,
                            est_audience=est_aud,
                            rules_url=row.get("rules_url", "").strip() or None,
                            frequency_cap=row.get("frequency_cap", "").strip() or None,
                            self_promo_allowed=row.get("self_promo_allowed", "true").lower() == "true",
                            link_policy=row.get("link_policy", "allowed").strip(),
                            disclosure_required=row.get("disclosure_required", "false").lower() == "true",
                            automation_allowed=row.get("automation_allowed", "true").lower() == "true",
                            relevance_score=float(row.get("relevance_score", 4.0) or 4.0),
                            relevance_reason=row.get("relevance_reason", "").strip() or None,
                            level=row.get("level", "L1").strip(),
                            instance_config={},
                        )
                        db.add(dest)
            except Exception as e:
                log.warning("seeder_csv_import_skipped", error=str(e))

        await db.commit()
        log.info("seeding_initial_destinations_completed")
