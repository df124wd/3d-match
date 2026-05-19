from typing import Optional, List, Generic, TypeVar
from datetime import datetime

from pydantic import BaseModel


T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int = 0
    message: str = "success"
    data: Optional[T] = None


class PointCloudInfo(BaseModel):
    file_path: str
    file_format: str
    point_count: str
    sampling_precision: str
    file_size: str
    description: Optional[str] = None


class IngestData(BaseModel):
    model_id: int
    pointcloud: PointCloudInfo
    vector_db_status: int
    vector_db_time: Optional[datetime] = None


class QueryData(BaseModel):
    model_id: int
    pointcloud: Optional[PointCloudInfo] = None
    vector_db_status: int
    vector_db_time: Optional[datetime] = None


class MatchItem(BaseModel):
    rank: int
    model_id: int
    model_name: Optional[str] = None
    part_name: Optional[str] = None
    project_id: Optional[int] = None
    project_name: Optional[str] = None
    distance: float
    similarity: float


class MatchData(BaseModel):
    query_filename: str
    top_k: int
    matches: List[MatchItem]


class HealthData(BaseModel):
    status: str
    faiss_loaded: bool
    faiss_vector_count: int
    mysql_connected: bool
