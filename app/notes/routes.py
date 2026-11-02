"""便签待办 API。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.notes import service

router = APIRouter(prefix="/api/notes", tags=["notes"])


class NoteBody(BaseModel):
    content: str = Field(min_length=1, max_length=500)


class DoneBody(BaseModel):
    done: bool


@router.get("")
def list_items() -> dict[str, Any]:
    service.init_notes()
    return {"items": service.list_notes()}


@router.post("")
def create_item(body: NoteBody) -> dict[str, Any]:
    service.init_notes()
    try:
        return service.create_note(body.content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.put("/{note_id}/done")
def mark_done(note_id: int, body: DoneBody) -> dict[str, Any]:
    service.init_notes()
    done = service.set_done(note_id, body.done)
    if done is None:
        raise HTTPException(status_code=404, detail="待办不存在")
    return {"ok": True, "done": done}


@router.delete("/{note_id}")
def delete_item(note_id: int) -> dict[str, Any]:
    service.init_notes()
    if not service.delete_note(note_id):
        raise HTTPException(status_code=404, detail="待办不存在")
    return {"ok": True}
