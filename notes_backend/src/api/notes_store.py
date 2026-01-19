import json
import os
import threading
from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


def _ensure_parent_dir(path: str) -> None:
    """Ensure the parent directory for a file path exists."""
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)


def _dt_to_iso(dt: datetime) -> str:
    """Serialize datetime to ISO-8601 string."""
    return dt.isoformat().replace("+00:00", "Z")


def _dt_from_iso(value: str) -> datetime:
    """Parse ISO-8601 string to datetime (best-effort)."""
    # datetime.fromisoformat supports "+00:00", not "Z" in older Pythons; handle both.
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


class NoteRecord(BaseModel):
    """Internal storage representation of a note."""

    id: UUID = Field(..., description="Unique note identifier.")
    title: str = Field(..., description="Note title.")
    content: str = Field(..., description="Note content.")
    created_at: datetime = Field(..., description="Created timestamp in UTC.")
    updated_at: datetime = Field(..., description="Updated timestamp in UTC.")


class NotesStore:
    """Thread-safe notes storage with optional JSON-file persistence."""

    def __init__(self, persist_path: str):
        self._persist_path = persist_path
        self._lock = threading.Lock()
        self._notes: Dict[UUID, NoteRecord] = {}
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        """Load notes from disk if persistence file exists."""
        if not self._persist_path:
            return
        path = os.path.abspath(self._persist_path)
        if not os.path.exists(path):
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            # Expected format: list[dict]
            if not isinstance(raw, list):
                return

            loaded: Dict[UUID, NoteRecord] = {}
            for item in raw:
                if not isinstance(item, dict):
                    continue
                try:
                    record = NoteRecord(
                        id=UUID(item["id"]),
                        title=str(item.get("title", "")),
                        content=str(item.get("content", "")),
                        created_at=_dt_from_iso(str(item["created_at"])),
                        updated_at=_dt_from_iso(str(item["updated_at"])),
                    )
                    loaded[record.id] = record
                except Exception:
                    # Skip malformed entries rather than failing startup.
                    continue

            with self._lock:
                self._notes = loaded
        except Exception:
            # Corrupted file shouldn't crash the service; start empty.
            return

    def _save_to_disk(self) -> None:
        """Persist notes to disk."""
        if not self._persist_path:
            return
        path = os.path.abspath(self._persist_path)
        _ensure_parent_dir(path)

        with self._lock:
            payload = [
                {
                    "id": str(n.id),
                    "title": n.title,
                    "content": n.content,
                    "created_at": _dt_to_iso(n.created_at),
                    "updated_at": _dt_to_iso(n.updated_at),
                }
                for n in self._notes.values()
            ]

        # Write atomically to reduce chance of corruption.
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp_path, path)

    def list_notes(self) -> List[NoteRecord]:
        """List notes sorted by updated_at descending."""
        with self._lock:
            notes = list(self._notes.values())
        notes.sort(key=lambda n: n.updated_at, reverse=True)
        return notes

    def get_note(self, note_id: UUID) -> Optional[NoteRecord]:
        """Get a note by id."""
        with self._lock:
            return self._notes.get(note_id)

    def create_note(self, record: NoteRecord) -> NoteRecord:
        """Create a new note."""
        with self._lock:
            self._notes[record.id] = record
        self._save_to_disk()
        return record

    def update_note(self, note_id: UUID, title: str, content: str, updated_at: datetime) -> Optional[NoteRecord]:
        """Update an existing note."""
        with self._lock:
            existing = self._notes.get(note_id)
            if existing is None:
                return None
            updated = existing.model_copy(
                update={
                    "title": title,
                    "content": content,
                    "updated_at": updated_at,
                }
            )
            self._notes[note_id] = updated
        self._save_to_disk()
        return updated

    def delete_note(self, note_id: UUID) -> bool:
        """Delete a note. Returns True if deleted."""
        with self._lock:
            existed = note_id in self._notes
            if existed:
                self._notes.pop(note_id, None)
        if existed:
            self._save_to_disk()
        return existed
