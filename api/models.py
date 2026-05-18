from pydantic import BaseModel
from typing import Optional


class UploadResponse(BaseModel):
    job_id: str
    status: str
    filename: str


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str
    sources: list[str] = []


class FeedbackRequest(BaseModel):
    query_id: str
    thumbs_up: bool
    comment: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    services: dict[str, str]


class ErrorResponse(BaseModel):
    detail: str
    code: str
