# Endorsement Agent Demo

A portfolio demo of an agentic insurance-endorsement assistant: LangGraph tool loop, skills with progressive disclosure, a derived live status bar, near-lossless tool-result compression, human approval gate, and an eval harness. All data is mocked.

- [CLAUDE.md](CLAUDE.md) — working rules and build status
- [docs/PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md) — why this exists and what to avoid
- [DESIGN.md](DESIGN.md) — architecture
- [GLOSSARY.md](GLOSSARY.md) — terms
- [docs/adr](docs/adr) — decisions

Run locally (needs `.env`, see `.env.example`):

```
uv sync
uv run uvicorn endorsement_agent.api:create_app --factory --port 7860
```

then open http://localhost:7860. `uv run python -m endorsement_agent` is a terminal chat.

Deploy: `render.yaml` is a Render Blueprint built from the `Dockerfile` (ADR-0024, ADR-0027). Locally: `docker build -t endorsement-agent . && docker run --env-file .env -p 7860:7860 endorsement-agent`.
