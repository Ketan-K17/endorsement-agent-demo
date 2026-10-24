"""In-memory, append-only event store, one stream per case."""

from __future__ import annotations

from endorsement_agent.case_file import CaseFile, apply, fold
from endorsement_agent.events import CaseCreated, CaseEvent


class EventStore:
    def __init__(self) -> None:
        self._streams: dict[str, list[CaseEvent]] = {}
        self._cases: dict[str, CaseFile] = {}

    def create(self, event: CaseCreated) -> CaseFile:
        if event.case_id in self._streams:
            raise ValueError(f"case {event.case_id} already exists")
        stored = event.model_copy(update={"seq": 1})
        self._streams[event.case_id] = [stored]
        self._cases[event.case_id] = fold([stored])
        return self._cases[event.case_id]

    def append(self, case_id: str, event: CaseEvent) -> CaseFile:
        """Assign the next seq, apply the event, store it, and return the new Case File.

        The event is stored only if it applies cleanly, so the stream always folds.
        """
        stream = self._streams[case_id]
        stored = event.model_copy(update={"seq": len(stream) + 1})
        case = apply(self._cases[case_id], stored)
        stream.append(stored)
        self._cases[case_id] = case
        return case

    def case(self, case_id: str) -> CaseFile:
        return self._cases[case_id]

    def events(self, case_id: str, after_seq: int = 0) -> list[CaseEvent]:
        return [e for e in self._streams[case_id] if e.seq > after_seq]
