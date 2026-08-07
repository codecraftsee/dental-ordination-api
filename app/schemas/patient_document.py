from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class PatientDocumentResponse(BaseModel):
    id: str
    patient_id: str
    filename: str
    content_type: str
    size_bytes: int
    description: Optional[str] = None
    uploaded_by_user_id: Optional[str] = None
    uploaded_at: datetime
    signed_url: str

    model_config = ConfigDict(from_attributes=True)
