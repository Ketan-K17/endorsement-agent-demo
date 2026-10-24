---
name: escalation-policy
description: Use when deciding whether to hand the case to a human.
tools_hint: [handover]
---
# Escalation

Hand over when
- a rule's `handover_if` applies (high if it suggests fraud, else medium);
- the policy is lapsed or not found after one recheck (low);
- documents contradict the policy on identity or vehicle (high);
- the ask budget is spent and something still blocks submission (medium);
- the user asks for a human (low).

Note: team `endorsements-ops`, one-line reason citing the facts. Then tell the user a person will follow up within one working day.
