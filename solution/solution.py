"""
Knowledge system for the interface.ai build assignment.

    build() -> KnowledgeSystem with ingest(snapshot), answer(question, as_of), conflicts()

The rules behind every decision are in docs/RULES.md. Layout:
    kb/store.py      every version of every page, plus snapshot-by-date lookup (R1)
    kb/authority.py  page trust tiers from the URL (R2)
    kb/dates.py      dates printed on the page (R3)
    kb/index.py      BM25 per snapshot, re-ranked by authority
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
_harness = next((d / "harness" for d in _HERE.parents if (d / "harness" / "contract.py").exists()), None)
if _harness:
    sys.path.insert(0, str(_harness))
from contract import Answer, Conflict, Snapshot, Source  # noqa: E402

from kb.index import SnapshotIndex  # noqa: E402
from kb.store import Store  # noqa: E402

REFUSAL = ("I'm not able to confirm that from Dupaco's website, so I don't want to guess. "
           "Please contact Dupaco or visit a branch for the current details.")


class KnowledgeSystem:
    def __init__(self):
        self.store = Store()
        self.indexes = {}          # snapshot_id -> SnapshotIndex
        self._tokens = {}          # chunk text -> token counts, shared across snapshots

    # -- contract ---------------------------------------------------------------------------
    def ingest(self, snapshot: Snapshot) -> None:
        view = self.store.add(snapshot)
        self.indexes[view.snapshot_id] = SnapshotIndex(view, self._tokens)

    def answer(self, question, as_of=None):
        view = self.store.at(as_of)
        hits = self.indexes[view.snapshot_id].search(question, k=5)
        if not hits:
            return Answer(text=REFUSAL, confident=False)
        _, page, passage = hits[0]
        return Answer(text=passage[:600],
                      sources=[Source(url=page.url, snapshot_id=page.snapshot_id, quote=passage[:200])])

    def conflicts(self):
        return []


def build():
    return KnowledgeSystem()
