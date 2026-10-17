# AI Usage Disclosure — IncuBrix Assessment 4

## AI Tools Used

| Tool | Purpose | Where |
|------|---------|-------|
| Google Gemini (optional) | Content tailoring, rules capture, relevance scoring | `api/services/ai_adapter/gemini.py` |
| Mock AI adapter (default) | Testing without API keys | `api/services/ai_adapter/mock.py` |

## How AI Is Used

1. **Rules Capture** (`POST /api/v1/rules/capture`): AI reads a community's rules page and *proposes* posting rules. Proposals are **never active** until a human confirms them via `POST /api/v1/rules/{id}/confirm`.

2. **Relevance Scoring** (catalogue import): AI scores destinations 1–5 for relevance to IncuBrix's audience. Used for sorting only — does not block publishing.

3. **Content Tailoring**: AI adapts title/body for a specific destination's format limits and tone. Original content is preserved; tailored version is a copy.

## Core Independence

**Core functionality does NOT depend on any AI model.** The rules engine, connectors, idempotency, certification, and all publishing logic work with the mock adapter (no API key needed).

## AI-Generated Content Flag

Every publish request includes `is_ai_generated: bool`. When true and the destination requires disclosure, the rules engine enforces adding an AI disclosure notice before publishing.

Every result manifest (`manifest.json`) includes an `ai_generated` boolean flag.
