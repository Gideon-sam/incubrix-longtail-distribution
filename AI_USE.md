# AI Usage Disclosure — IncuBrix Assessment 4

## AI Assistants & Coding Tools

| Tool / Model | Creator | Purpose in Submission |
|--------------|---------|-----------------------|
| Google Antigravity | Google DeepMind | Agentic AI coding assistant used for architectural refactoring, hardening, connector integration, test suite authoring, and documentation. |
| Google Gemini 1.5 Flash / 2.5 Flash | Google | LLM provider used in `api/services/ai_adapter/gemini.py` for rules capture, content tailoring, and catalogue relevance scoring. |
| Claude (Anthropic) | Anthropic | Used interactively during design exploration and code review for rules-engine logic and edge-case reasoning. |
| ChatGPT / GPT-4o (OpenAI) | OpenAI | Used for drafting documentation, reviewing error-code mappings, and exploring connector architecture options. |
| Mock AI Adapter (Built-in) | IncuBrix | Offline mock adapter providing zero-cost, zero-API-key deterministic rule proposals, word-boundary truncation, and scoring for tests. |

## How AI Is Used in the Running System

1. **Rules Capture (`POST /api/v1/rules/capture`)**:
   - AI inspects community guideline web pages or markdown text and drafts rule proposals.
   - Proposals remain in `proposed` status and are **never active** until confirmed by a human administrator via `POST /api/v1/rules/{proposal_id}/confirm`.

2. **Relevance Scoring (`catalogue/real_destinations.csv`)**:
   - Scores destinations 1–5 based on audience alignment with creator content.
   - Used exclusively for ranking and recommendation filtering; never used to hard-block publishing.

3. **Content Tailoring (`POST /api/v1/tailor`)**:
   - Formats content according to destination-specific guidelines (e.g. discussion-first framing on Discourse, character length compliance on Dev.to).
   - Preserves non-English characters and formatting; original content remains untouched in the rendition object.

## Core System Independence

Core distribution and publishing logic does **not** require any live AI model. The system operates fully deterministically in offline environments using the included mock adapter (`LLM_PROVIDER=mock`). All 74 tests pass with zero external network access and zero API keys.

## Disclosure & Rights Compliance

- Every publish request accepts `is_ai_generated: bool`.
- When `is_ai_generated=True` and a destination specifies `disclosure_required=True`, the rules engine enforces disclosure (either blocking undisclosed content or auto-appending an explicit disclosure notice if `AUTO_DISCLOSURE=true`).
- Every cryptographic output manifest (`manifest.json`) records the `ai_generated` flag and estimated token costs.
