"""
Pydantic models for NCR Upload API
"""
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime


class JobRequest(BaseModel):
    """Request model for job processing"""
    job_id: str
    username: str
    campaign: str
    row_id: Optional[int] = None


class JobResponse(BaseModel):
    """Response model for job processing"""
    job_id: str
    status: str
    message: str
    timestamp: datetime
    task_id: str


class JobStatusResponse(BaseModel):
    """Response model for job status"""
    job_id: str
    task_id: str
    status: str
    progress: Dict[str, Any]
    message: str
    timestamp: datetime


class HealthResponse(BaseModel):
    """Response model for health check"""
    status: str
    redis: str
    database: str
    timestamp: datetime


class ActiveJobsResponse(BaseModel):
    """Response model for active jobs"""
    active_jobs: list
    count: int


class FileUploadRequest(BaseModel):
    """Request model for file upload processing"""
    job_id: str
    row_id: Optional[int] = None


class FileUploadResponse(BaseModel):
    """Response model for file upload processing"""
    job_id: str
    status: str
    message: str
    timestamp: datetime
    task_id: str
    upload_count: Optional[int] = None


class FileUploadStatusResponse(BaseModel):
    """Response model for file upload status"""
    job_id: str
    task_id: str
    status: str
    progress: Dict[str, Any]
    message: str
    timestamp: datetime
    upload_count: Optional[int] = None
    file_status: Optional[str] = None
    qc_status: Optional[str] = None


# Job status constants
class JobStatus:
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    VALIDATION_PASSED = "validation_passed"
    VALIDATION_FAILED = "validation_failed"
    UPLOADING = "uploading"
    FILE_UPLOAD_PENDING = "file_upload_pending"
    FILE_UPLOAD_PROCESSING = "file_upload_processing"
    FILE_UPLOAD_COMPLETED = "file_upload_completed"
    FILE_UPLOAD_FAILED = "file_upload_failed"
