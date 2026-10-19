"""
Destination auto-seeder.

Ensures that fresh environments (docker-compose, local testing, assessment test runner)
start with a populated catalogue containing core destinations for all 9 connectors
and the full 150+ real-world destinations from catalogue/real_destinations.csv.

Phase 1.5 compliance:
- Seeded and imported destinations start at L0 (catalogued), or L1 if automation_allowed=false (assisted).
- last_certified_at stays NULL until an actual /certify run passes.
"""
from __future__ import annotations
import csv
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select, func
from api.database import async_session
from api.models.destination import Destination
from api.middleware.logging_mw import get_logger
from api.config import settings

log = get_logger("services.seeder")

# Allowed automated hosts list from env
ALLOWED_HOSTS = [h.strip().lower() for h in settings.ALLOWED_AUTOMATED_HOSTS.split(",") if h.strip()]


def is_host_allowlisted(url: str) -> bool:
    """Check if URL belongs to allowlisted automated hosts."""
    try:
        parsed = urlparse(url)
        host_with_port = parsed.netloc.lower()
        full_origin = f"{parsed.scheme}://{host_with_port}".lower()
        for allowed in ALLOWED_HOSTS:
            al_parsed = urlparse(allowed)
            al_origin = f"{al_parsed.scheme}://{al_parsed.netloc}".lower()
            if full_origin == al_origin or host_with_port == al_parsed.netloc.lower():
                return True
        return False
    except Exception:
        return False


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
        "frequency_cap": "20/day",
        "self_promo_allowed": True,
        "link_policy": "allowed",
        "disclosure_required": False,
        "automation_allowed": True,
        "relevance_score": 5.0,
        "relevance_reason": "Top developer publishing community",
        "level": "L0",
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
        "frequency_cap": "20/day",
        "self_promo_allowed": False,
        "link_policy": "allowed",
        "disclosure_required": False,
        "automation_allowed": True,
        "relevance_score": 4.5,
        "relevance_reason": "High-engagement forum community",
        "level": "L0",
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
        "frequency_cap": "20/day",
        "self_promo_allowed": False,
        "link_policy": "allowed",
        "disclosure_required": False,
        "automation_allowed": True,
        "relevance_score": 4.0,
        "relevance_reason": "Federated community network",
        "level": "L0",
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
        "level": "L0",
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
        "level": "L0",
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
        "level": "L0",
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
        "level": "L0",
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
        "level": "L0",
        "instance_config": {"feed_name": "default"},
    },
]


async def seed_initial_destinations():
    """Populate destinations table and ensure core destinations & frequency caps are synced."""
    async with async_session() as db:
        res = await db.execute(select(Destination.id))
        existing_ids = set(res.scalars().all())

        log.info("seeding_initial_destinations", existing_count=len(existing_ids))

        # 1. Add core destinations for all connectors or update frequency caps
        for item in CORE_DESTINATIONS:
            if item["id"] in existing_ids:
                dest_res = await db.execute(select(Destination).where(Destination.id == item["id"]))
                curr = dest_res.scalar_one_or_none()
                if curr and item.get("frequency_cap"):
                    curr.frequency_cap = item["frequency_cap"]
                continue

            level = "L1" if not item.get("automation_allowed", True) else "L0"
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
                status="active",
                relevance_score=item.get("relevance_score", 4.0),
                relevance_reason=item.get("relevance_reason"),
                level=level,
                instance_config=item.get("instance_config", {}),
                last_certified_at=None,
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
                        if any(str(c.get("url", "")).rstrip("/") == url for c in CORE_DESTINATIONS):
                            continue

                        tags = [t.strip() for t in row.get("audience_tags", "").split(",") if t.strip()]
                        aud_str = row.get("est_audience", "")
                        est_aud = None
                        if aud_str:
                            try:
                                est_aud = int(float(aud_str))
                            except (ValueError, TypeError):
                                est_aud = None

                        auto_allowed = row.get("automation_allowed", "true").lower() == "true"
                        is_allowlisted = is_host_allowlisted(url)

                        # Real catalogue destinations outside our owned hosts route to assisted
                        if not auto_allowed or not is_allowlisted:
                            connector_key = "assisted"
                            level = "L1" if not auto_allowed else "L0"
                        else:
                            connector_key = row.get("connector_key", "assisted").strip()
                            level = "L0"

                        rel_score = 4.0
                        if row.get("relevance_score"):
                            try:
                                parsed_rel = float(row.get("relevance_score"))
                                if parsed_rel == parsed_rel:  # not NaN
                                    rel_score = parsed_rel
                            except (ValueError, TypeError):
                                rel_score = 4.0

                        dest = Destination(
                            name=name,
                            url=url,
                            platform_key=row.get("platform_key", "assisted").strip(),
                            connector_key=connector_key,
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
                            automation_allowed=auto_allowed,
                            status="active",
                            relevance_score=rel_score,
                            relevance_reason=row.get("relevance_reason", "").strip() or None,
                            level=level,
                            last_certified_at=None,
                            instance_config={},
                        )
                        db.add(dest)
            except Exception as e:
                log.warning("seeder_csv_import_skipped", error=str(e))

        await db.commit()
        log.info("seeding_initial_destinations_completed")
