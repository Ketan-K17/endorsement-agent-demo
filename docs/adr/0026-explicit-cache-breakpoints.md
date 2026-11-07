# ADR-0026: Explicit prompt-cache breakpoints on the agent

Status: accepted (by the user, 2026-11-07)

**Context.** DESIGN §2 and ADR-0003 assume a longest-prefix cache: the status bar breaks only the tail, so everything above it stays cached and the cached prefix grows each step. On the GPT-5.6 agent deployment, Azure caches only at breakpoints. By default it places one on the latest message, our status bar, which no later call contains. A read matches only a breakpoint that is present in the request. In case-60cbc143, 23 agent calls each read the static 1,963 tokens and wrote the rest again (57k tokens written, about 130k total). A probe on 2026-11-07 confirmed it: in the app's pattern the read stayed at the static prefix; with breakpoints kept in place each step read everything before the status bar and wrote only the new step (about 47 tokens).

**Decision.** The agent's model calls only:

- `prompt_cache_options: {mode: explicit}` and `prompt_cache_key` = case id, as request-body extras on the agent model.
- `model_input` marks breakpoints when the prompt is rendered: on the system message, and on each stored message that ended an earlier call's history (the one before each assistant message) and on the last stored message. The marks are derived from the history alone, so every call places the same ones; they are never stored.
- The status bar stays last, unmarked, and is the only part processed fresh.
- The other roles (`gpt-5` and older) get none of this: those models reject the options with a 400.
- The per-case and daily token meters (ADR-0025) count tokens minus cache reads. Sized on case-e32750e8, the largest demo (39k by this count), `SESSION_MAX_TOKENS` drops from 150k to 100k.

**Consequences.** Invariants 1–3 hold: same order, bar last and never stored, history unchanged. Breakpoints on assistant messages are ignored by the service; none are needed, as the message before a bar is never an assistant one. Image stubbing and compression rewrite older messages, so the cache misses once from the rewritten point (as ADR-0004 accepts). Azure reads at most the latest 50 breakpoints and writes 4 per request; a case has far fewer steps. A deployment that does not support breakpoints must not get them: changing the agent model to a pre-5.6 one needs this turned off.
