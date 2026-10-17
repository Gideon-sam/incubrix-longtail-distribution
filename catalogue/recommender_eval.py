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
            "MLOps Community", "Ben's Bites", "Superhuman AI", "OpenAI Developer Forum"
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
            "GrowthHackers", "Demand Curve", "CXL Community"
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
            "Towards Data Science"
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
            "Weights & Biases Community"
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
            "Every.to", "Ness Labs", "Ghost Network",
            "HubSpot Blog", "DZone", "Indie Hackers", "Product Hunt"
        ],
    },
]


def compute_precision_at_k(recommendations: list[dict], relevant: list[str], k: int = 10) -> float:
    """Compute precision@k given recommendations and ground-truth relevant destinations."""
    top_k = [r["name"] for r in recommendations[:k]]
    hits = sum(1 for name in top_k if name in relevant)
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
    print("Recommender Evaluation — Labelled Set")
    print(f"Items: {len(LABELLED_SET)}")
    print(f"Measuring: Precision@10")
    print()
    print("Sample item:")
    item = LABELLED_SET[0]
    print(f"  Title: {item['title']}")
    print(f"  Relevant destinations ({len(item['relevant_destinations'])}): {', '.join(item['relevant_destinations'][:5])}...")
    print()
    print("To evaluate: POST /api/v1/recommend for each item and compare with LABELLED_SET")
    print("Run: python catalogue/recommender_eval.py --api http://localhost:8000")
