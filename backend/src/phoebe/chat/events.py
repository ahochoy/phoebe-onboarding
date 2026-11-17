"""Wire shapes of the chat SSE events, shared by the service and the OpenAPI
export. Field order is the wire order; the JSON must not change shape."""

from pydantic import BaseModel

from phoebe.chat.refusals import RefusalCode
from phoebe.chat.verify import Citation


class MetaEvent(BaseModel):
    turn_id: str


class DeltaEvent(BaseModel):
    text: str


class ClosestDoc(BaseModel):
    document_id: str
    title: str


class DoneEvent(BaseModel):
    text: str
    refused: bool
    # The public refusal code (see chat/refusals.py), never the internal name.
    reason: RefusalCode | None
    citations: list[Citation]
    closest: list[ClosestDoc]


class ErrorEvent(BaseModel):
    code: str
