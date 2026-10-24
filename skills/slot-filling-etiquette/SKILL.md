---
name: slot-filling-etiquette
description: Use when several values are still missing or the user's answers conflict.
tools_hint: [ask_user, record_slot, get_case]
---
# Slot-filling etiquette

- One ask per batch: list every missing item, numbered, in one reply.
- Record each value the moment it is given, source `user_msg`, confidence 0.9 unless hedged.
- A document value beats a typed one only if more confident; otherwise supersede with a reason.
- Conflicting answers: quote both and ask which is right. Don't pick silently.
- Budget nearly gone: ask only for what blocks submission.
