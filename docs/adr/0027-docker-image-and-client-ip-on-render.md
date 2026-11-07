# ADR-0027: Docker image, Render Blueprint, and the client IP behind Render

Status: proposed (2026-11-07)

**Context.** ADR-0024 hosts the demo on a Render free web service built from a Dockerfile. ADR-0025 counts started cases per IP and left the client IP to deploy configuration: "uvicorn must trust the proxy's forwarded headers". Render's proxy appends to an incoming `X-Forwarded-For` instead of replacing it (Render community and feedback threads, 2026-11; not in Render's docs), and uvicorn with `--forwarded-allow-ips '*'` takes the first entry. A visitor could then forge a new IP on every request and skip the per-IP cap. Render sits behind Cloudflare, which sets `CF-Connecting-IP` to the address it saw and overwrites any value the visitor sent.

**Decision.**

- **Client IP:** a new setting `CLIENT_IP_HEADER` names the header that holds the visitor's address. When it is set and the header is present, that value is the IP; otherwise the peer address. The app never reads `X-Forwarded-For` for the IP. Unset by default, so a local run cannot be fooled by a header; Render sets it to `cf-connecting-ip`.
- **Proxy headers:** uvicorn still runs with `--proxy-headers --forwarded-allow-ips '*'`, only so `X-Forwarded-Proto` makes the scheme https and the owner cookie gets `Secure`. The container is reachable only through Render's proxy.
- **Image:** `python:3.12-slim`, dependencies from `uv.lock` (`uv sync --frozen --no-dev`), run as a non-root user, port from `PORT`. The project runs from `/app` as source, because the app reads `skills/` and `fixtures/documents/` beside `src/`. `.dockerignore` is an allow-list, so `.env` and `private_docs/` never enter a build.
- **Blueprint:** `render.yaml` declares one free web service in Singapore (nearest the India agent resource), health check `/`, auto-deploy off. Keys, endpoints and `INVITE_CODE` are `sync: false`: asked for once at creation, never in git. Deployments, `FIXED_TODAY` and `CLIENT_IP_HEADER` are literal. Limits keep the app's defaults unless set in the dashboard.

**Consequences.** The `CF-Connecting-IP` behaviour must be checked live after the first deploy: two networks should count as two IPs, and a forged `X-Forwarded-For` should not change the count. If Render ever serves without Cloudflare in front, the header is absent and every visitor falls back to the proxy's address, which fails closed (one shared quota) rather than open. Opening a case is still not counted per IP (ADR-0025), so one client can fill the 40 live slots until they expire; left as is for now. Changing a `sync: false` value later is a dashboard edit, since Blueprint syncs ignore them.
