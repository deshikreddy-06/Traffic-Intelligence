from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class AreaBase(BaseModel):
    name: str
    display_name: str
    latitude: float
    longitude: float
    is_active: bool = True

class AreaCreate(AreaBase):
    pass

class Area(AreaBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
