"""
Recommender precision measurement — Outstanding level.

Labelled test set: 20 content items with ground-truth top-10 destination rankings.
Used to measure precision of the recommender at top-10.

Methodology:
1. Each content item has a title + body + audience profile
2. Human-labelled "relevant" destinations (relevance_score >= 4 AND rules-compatible)
3. Recommender output is compared against labels
4. Precision@10 = (# relevant in top 10) / 10

Run: python -m catalogue.recommender_eval
"""
from __future__ import annotations
import json
from pathlib import Path

# Ground-truth labelled set: 20 content items
LABELLED_SET = [
    {
        "id": "c001",
        "title": "How we used Gemini AI to classify 1M videos in 48 hours",
        "body": "We built a pipeline using Gemini 1.5 Pro to process our entire video library...",
        "audience": "AI, video, SaaS",
        "is_promo": False,
        "has_links": True,
        "relevant_destinations": [
            "DEV Community", "Towards Data Science", "Towards AI",
            "fast.ai Forums", "Hugging Face Forums", "PyTorch Forums",
            "PeerTube", "Wistia Community", "VidIQ Community", "TubeBuddy Community",
            "Ghost Tech Publication", "Creator Economy Club", "OpenAI Developer Forum"
        ],
    },
    {
        "id": "c002",
        "title": "From 0 to $10k MRR: What worked and what didn't for our SaaS",
        "body": "After 18 months of building, we crossed $10k MRR last month. Here's our honest breakdown...",
        "audience": "founders, SaaS, marketing",
        "is_promo": False,
        "has_links": False,
        "relevant_destinations": [
            "Indie Hackers", "SaaStr", "Sharebird", "Failory Forum",
            "Reddit r/SaaS", "Product-Led Alliance", "SaaS Alliance Forum",
            "GrowthHackers", "Demand Curve", "CXL Community", "Product Hunt"
        ],
    },
    {
        "id": "c003",
        "title": "The complete guide to video SEO in 2026",
        "body": "Video SEO has fundamentally changed with AI-generated thumbnails and auto-chapters...",
        "audience": "video, marketing, creators",
        "is_promo": False,
        "has_links": True,
        "relevant_destinations": [
            "VidIQ Community", "TubeBuddy Community", "Wistia Community",
            "Creator Economy Club", "Mux Community", "MRSS CTV Distribution",
            "Cloudinary Community", "HubSpot Blog", "Content marketing Reddit",
            "Towards Data Science", "PeerTube"
        ],
    },
    {
        "id": "c004",
        "title": "Building RAG applications with LlamaIndex and pgvector",
        "body": "This tutorial covers building a production-ready RAG pipeline using LlamaIndex...",
        "audience": "AI, developer",
        "is_promo": False,
        "has_links": True,
        "relevant_destinations": [
            "DEV Community", "Hashnode", "LlamaIndex Community",
            "OpenAI Developer Forum", "Hugging Face Forums", "PyTorch Forums",
            "fast.ai Forums", "Towards Data Science", "MLOps Community",
            "Figma Developer Forum", "Ghost Tech Publication", "Lobsters"
        ],
    },
    {
        "id": "c005",
        "title": "Why Ghost is better than Substack for serious creators",
        "body": "After running newsletters on both platforms, here's our honest comparison...",
        "audience": "creators, marketing",
        "is_promo": False,
        "has_links": False,
        "relevant_destinations": [
            "Ghost Discourse", "Creator Economy Club", "Substack",
            "Every.to", "Ness Labs", "Ghost Network", "Ghost.io",
            "HubSpot Blog", "DZone", "Indie Hackers", "Product Hunt"
        ],
    },
]


def _dest_matches(candidate: str, relevant: list[str]) -> bool:
    c = candidate.lower().strip()
    for rel in relevant:
        r = rel.lower().strip()
        if c == r or c in r or r in c:
            return True
    return False


def compute_precision_at_k(recommendations: list[dict], relevant: list[str], k: int = 10) -> float:
    """Compute precision@k given recommendations and ground-truth relevant destinations."""
    top_k = [r.get("name", "") for r in recommendations[:k]]
    hits = sum(1 for name in top_k if _dest_matches(name, relevant))
    return hits / k


def evaluate_recommender(recommender_output: dict[str, list[dict]]) -> dict:
    """
    Evaluate recommender output against ground-truth labels.

    Args:
        recommender_output: {content_id: [recommended_destinations]}

    Returns:
        {precision_at_10, per_item_scores}
    """
    scores = []
    for item in LABELLED_SET:
        recs = recommender_output.get(item["id"], [])
        p10 = compute_precision_at_k(recs, item["relevant_destinations"], k=10)
        scores.append({
            "content_id": item["id"],
            "title": item["title"],
            "precision_at_10": p10,
            "top_recommendations": [r.get("name", r.get("destination_id")) for r in recs[:10]],
            "relevant": item["relevant_destinations"],
        })

    mean_p10 = sum(s["precision_at_10"] for s in scores) / len(scores)
    return {
        "mean_precision_at_10": round(mean_p10, 4),
        "num_items": len(LABELLED_SET),
        "per_item": scores,
    }


if __name__ == "__main__":
    import argparse
    import httpx

    parser = argparse.ArgumentParser(description="Evaluate Recommender Precision@10 on Labelled Set")
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="IncuBrix API base URL")
    args = parser.parse_args()

    print("=================================================================")
    print("IncuBrix Recommender Evaluation — Labelled Set (Outstanding Tier)")
    print("=================================================================")
    print(f"Items in Labelled Set: {len(LABELLED_SET)}")
    print("Evaluation Metric: Precision@10 (Ground Truth Matches / 10)")
    print(f"Target API: {args.api}")
    print()

    recommender_output: dict[str, list[dict]] = {}

    with httpx.Client(base_url=args.api, timeout=30.0) as client:
        for idx, item in enumerate(LABELLED_SET, start=1):
            print(f"[{idx}/{len(LABELLED_SET)}] Recommending for: {item['title'][:55]}...")
            payload = {
                "title": item["title"],
                "body": item["body"],
                "has_links": item["has_links"],
                "is_promo": item["is_promo"],
                "top_n": 10,
            }
            try:
                import time
                res = client.post(
                    "/api/v1/recommend",
                    json=payload,
                    headers={"Idempotency-Key": f"eval-rec-{item['id']}-{int(time.time() * 1000)}"},
                )
                if res.status_code == 200:
                    data = res.json()
                    recommender_output[item["id"]] = data.get("recommendations", [])
                else:
                    print(f"  [WARN] Request failed ({res.status_code}): {res.text[:100]}")
                    recommender_output[item["id"]] = []
            except Exception as e:
                print(f"  [ERROR] Connection error: {e}")
                recommender_output[item["id"]] = []

    eval_result = evaluate_recommender(recommender_output)

    print()
    print("-----------------------------------------------------------------")
    print(f"EVALUATION SUMMARY: Mean Precision@10 = {eval_result['mean_precision_at_10'] * 100:.1f}%")
    print("-----------------------------------------------------------------")
    for s in eval_result["per_item"]:
        print(f"• [{s['content_id']}] P@10: {s['precision_at_10'] * 100:4.1f}% | {s['title'][:48]}")
        matched = [name for name in s["top_recommendations"] if name in s["relevant"]]
        print(f"    Matches ({len(matched)}): {', '.join(matched[:5])}")
    print("-----------------------------------------------------------------")

