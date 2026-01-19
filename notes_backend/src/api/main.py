import os
from datetime import datetime, timezone
from typing import List
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Path, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.api.notes_store import NoteRecord, NotesStore


def _utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


PERSIST_PATH_DEFAULT = os.path.join(os.path.dirname(__file__), "..", "..", "data", "notes.json")


app = FastAPI(
    title="Simple Notes API",
    description=(
        "A simple notes service (no auth) supporting CRUD operations for notes.\n\n"
        "Each note has a title, content, created_at, and updated_at."
    ),
    version="1.0.0",
    openapi_tags=[
        {"name": "Health", "description": "Service health endpoints."},
        {"name": "Notes", "description": "CRUD operations for notes."},
    ],
)

# Environment-driven configuration with sensible defaults.
# NOTE: If you want a different location, set NOTES_PERSIST_PATH in .env for notes_backend.
PERSIST_PATH = os.getenv("NOTES_PERSIST_PATH", PERSIST_PATH_DEFAULT)

# NOTE: In production you should restrict this. For preview/dev we allow localhost:3000 by default.
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in CORS_ORIGINS if o.strip()] or ["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = NotesStore(persist_path=PERSIST_PATH)


class NoteBase(BaseModel):
    """Shared fields for note create/update."""

    title: str = Field(..., min_length=1, max_length=200, description="Short title for the note.")
    content: str = Field(..., min_length=0, max_length=50_000, description="Full note content.")


class NoteCreate(NoteBase):
    """Request model for creating a note."""

    model_config = {"json_schema_extra": {"examples": [{"title": "Shopping list", "content": "Milk\nEggs\nBread"}]}}


class NoteUpdate(NoteBase):
    """Request model for updating a note."""

    model_config = {"json_schema_extra": {"examples": [{"title": "Updated title", "content": "Updated content"}]}}


class NoteOut(NoteBase):
    """Response model for a note."""

    id: UUID = Field(..., description="Unique note identifier.")
    created_at: datetime = Field(..., description="UTC time when the note was created.")
    updated_at: datetime = Field(..., description="UTC time when the note was last updated.")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": "b6c7b7b4-7a33-4f0d-bf2d-26f8df1b9c3e",
                    "title": "Shopping list",
                    "content": "Milk\nEggs\nBread",
                    "created_at": "2026-01-01T12:00:00Z",
                    "updated_at": "2026-01-01T12:00:00Z",
                }
            ]
        }
    }


class ErrorResponse(BaseModel):
    """Standard error response payload."""

    detail: str = Field(..., description="Human-readable error message.")


# PUBLIC_INTERFACE
@app.get(
    "/",
    tags=["Health"],
    summary="Health check",
    description="Basic health check endpoint.",
)
def health_check():
    """Health check endpoint returning a simple status payload."""
    return {"message": "Healthy"}


# PUBLIC_INTERFACE
@app.get(
    "/notes",
    response_model=List[NoteOut],
    tags=["Notes"],
    summary="List notes",
    description="Return all notes ordered by updated_at descending.",
)
def list_notes():
    """List all notes."""
    notes = store.list_notes()
    return [NoteOut(**n.model_dump()) for n in notes]


# PUBLIC_INTERFACE
@app.get(
    "/notes/{note_id}",
    response_model=NoteOut,
    responses={404: {"model": ErrorResponse, "description": "Note not found"}},
    tags=["Notes"],
    summary="Get note",
    description="Get a single note by its id.",
)
def get_note(
    note_id: UUID = Path(..., description="Note UUID"),
):
    """Fetch a single note by id."""
    note = store.get_note(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return NoteOut(**note.model_dump())


# PUBLIC_INTERFACE
@app.post(
    "/notes",
    response_model=NoteOut,
    status_code=201,
    tags=["Notes"],
    summary="Create note",
    description="Create a new note with title and content.",
)
def create_note(payload: NoteCreate):
    """Create a note."""
    now = _utc_now()
    record = NoteRecord(
        id=uuid4(),
        title=payload.title.strip(),
        content=payload.content,
        created_at=now,
        updated_at=now,
    )
    created = store.create_note(record)
    return NoteOut(**created.model_dump())


# PUBLIC_INTERFACE
@app.put(
    "/notes/{note_id}",
    response_model=NoteOut,
    responses={404: {"model": ErrorResponse, "description": "Note not found"}},
    tags=["Notes"],
    summary="Update note",
    description="Update an existing note's title and content.",
)
def update_note(
    payload: NoteUpdate,
    note_id: UUID = Path(..., description="Note UUID"),
):
    """Update a note by id."""
    updated = store.update_note(
        note_id=note_id,
        title=payload.title.strip(),
        content=payload.content,
        updated_at=_utc_now(),
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return NoteOut(**updated.model_dump())


# PUBLIC_INTERFACE
@app.delete(
    "/notes/{note_id}",
    status_code=204,
    responses={404: {"model": ErrorResponse, "description": "Note not found"}},
    tags=["Notes"],
    summary="Delete note",
    description="Delete a note by id.",
)
def delete_note(
    note_id: UUID = Path(..., description="Note UUID"),
):
    """Delete a note by id."""
    deleted = store.delete_note(note_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Note not found")
    return Response(status_code=204)
