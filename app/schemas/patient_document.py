from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PatientDocumentResponse(BaseModel):
    id: str
    patient_id: str
    filename: str
    content_type: str
    size_bytes: int
    description: str | None = None
    uploaded_by_user_id: str | None = None
    uploaded_at: datetime
    signed_url: str

    model_config = ConfigDict(from_attributes=True)
