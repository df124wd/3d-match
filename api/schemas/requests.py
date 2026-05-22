# Request schemas — currently unused (parameters are Form/File fields in routers)
# Kept for future validation or batch API use.
from typing import Optional

from pydantic import BaseModel, Field


class IngestRequest(BaseModel):
    file_path: str = Field(..., description="3D model file path on server")
    creator: str = Field(..., max_length=64, description="Creator user ID or name")
    description: Optional[str] = Field(None, max_length=500, description="Point cloud description")


class MatchRequest(BaseModel):
    file_path: str = Field(..., description="Query 3D model file path on server")
    top_k: int = Field(5, ge=1, le=50, description="Number of results")
