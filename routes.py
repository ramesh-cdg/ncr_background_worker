"""
API routes module
"""
import os
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import Optional, List, Dict, Any

from models import (
    JobRequest, JobResponse, JobStatusResponse, 
    HealthResponse, ActiveJobsResponse, JobStatus
)
from database import DatabaseManager
from redis_manager import redis_manager
from celery_app import celery_app, memory_manager
from tasks import process_job_task, batch_process_jobs, health_check_task
from config import settings


# Create router
router = APIRouter()


# Batch processing models
class BatchJobRequest:
    """Request model for batch job processing"""
    def __init__(self, job_id: str, username: str, campaign: str, row_id: Optional[int] = None):
        self.job_id = job_id
        self.username = username
        self.campaign = campaign
        self.row_id = row_id


@router.get("/")
async def root():
    """Root endpoint"""
    return {"message": "NCR Upload API is running", "version": settings.api_version}


@router.post("/process-job", response_model=JobResponse)
async def process_job(job_request: JobRequest):
    """Process a job using Celery - always queue the job"""
    try:
        # Always queue the job - Celery will handle memory management
        # No need to check memory here as Celery has built-in concurrency control
        
        # Generate unique task ID
        task_id = str(uuid.uuid4())
        
        # Start Celery task
        celery_result = process_job_task.delay(
            job_request.job_id,
            job_request.username,
            job_request.campaign,
            job_request.row_id
        )
        
        # Create job status in Redis with Celery task ID
        redis_manager.create_job_status(
            job_request.job_id, 
            task_id, 
            job_request.username, 
            job_request.campaign, 
            job_request.row_id,
            celery_task_id=celery_result.id
        )
        
        return JobResponse(
            job_id=job_request.job_id,
            status="processing",
            message="Job processing started with Celery",
            timestamp=redis_manager.get_current_ny_time(),
            task_id=task_id
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/job-status/{task_id}", response_model=JobStatusResponse)
async def get_job_status_endpoint(task_id: str):
    """Get the status of a specific job by task ID"""
    try:
        job_data = redis_manager.get_job_status(task_id)
        if job_data:
            return JobStatusResponse(
                job_id=job_data["job_id"],
                task_id=task_id,
                status=job_data["status"],
                progress=job_data["progress"],
                message=job_data["message"],
                timestamp=datetime.fromisoformat(job_data["timestamp"])
            )
        else:
            raise HTTPException(status_code=404, detail="Job not found")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/job-status-by-job-id/{job_id}")
async def get_job_status_by_job_id(job_id: str):
    """Get the status of a job by job ID (returns latest task)"""
    try:
        return {
            "message": "Please use the task_id from the process-job response to check status",
            "job_id": job_id,
            "note": "Use /job-status/{task_id} endpoint with the task_id returned from /process-job"
        }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint with Celery integration"""
    try:
        # Get health status from Celery task
        health_result = health_check_task.delay()
        health_data = health_result.get(timeout=10)
        
        return HealthResponse(
            status=health_data.get("overall", "unknown"),
            redis=health_data.get("redis", "unknown"),
            database=health_data.get("database", "unknown"),
            timestamp=datetime.fromisoformat(health_data.get("timestamp", redis_manager.get_current_ny_time().isoformat()))
        )
    except Exception as e:
        # Fallback to basic health check
        try:
            redis_status = "healthy" if redis_manager.test_connection() else "unhealthy"
        except:
            redis_status = "unhealthy"
        
        try:
            conn = DatabaseManager.get_connection()
            conn.close()
            db_status = "healthy"
        except:
            db_status = "unhealthy"
        
        return HealthResponse(
            status="healthy" if redis_status == "healthy" and db_status == "healthy" else "degraded",
            redis=redis_status,
            database=db_status,
            timestamp=redis_manager.get_current_ny_time()
        )


@router.get("/jobs/active", response_model=ActiveJobsResponse)
async def get_active_jobs():
    """Get all active jobs from Redis"""
    try:
        active_jobs = redis_manager.get_active_jobs()
        return ActiveJobsResponse(active_jobs=active_jobs, count=len(active_jobs))
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/process-batch")
async def process_batch_jobs(job_requests: List[JobRequest]):
    """Process multiple jobs in batch with memory management"""
    try:
        # Check memory availability
        if not memory_manager.should_accept_new_job():
            raise HTTPException(
                status_code=503, 
                detail="Server memory usage is high. Please try again later."
            )
        
        # Convert to batch format
        batch_jobs = []
        for job_req in job_requests:
            batch_jobs.append({
                "job_id": job_req.job_id,
                "username": job_req.username,
                "campaign": job_req.campaign,
                "row_id": job_req.row_id
            })
        
        # Start batch processing
        batch_result = batch_process_jobs.delay(batch_jobs)
        
        return {
            "batch_id": batch_result.id,
            "total_jobs": len(job_requests),
            "status": "processing",
            "message": f"Batch processing started for {len(job_requests)} jobs",
            "timestamp": redis_manager.get_current_ny_time()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/batch-status/{batch_id}")
async def get_batch_status(batch_id: str):
    """Get batch processing status"""
    try:
        from celery.result import AsyncResult
        result = AsyncResult(batch_id, app=celery_app)
        
        if result.ready():
            if result.successful():
                return {
                    "batch_id": batch_id,
                    "status": "completed",
                    "result": result.result,
                    "timestamp": redis_manager.get_current_ny_time()
                }
            else:
                return {
                    "batch_id": batch_id,
                    "status": "failed",
                    "error": str(result.result),
                    "timestamp": redis_manager.get_current_ny_time()
                }
        else:
            return {
                "batch_id": batch_id,
                "status": "processing",
                "message": "Batch is still being processed",
                "timestamp": redis_manager.get_current_ny_time()
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/memory-stats")
async def get_memory_stats():
    """Get current memory statistics"""
    try:
        memory_stats = memory_manager.get_memory_usage()
        return {
            "memory_stats": memory_stats,
            "recommended_concurrency": memory_manager.get_recommended_concurrency(),
            "can_accept_jobs": memory_manager.should_accept_new_job(),
            "timestamp": redis_manager.get_current_ny_time()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/celery-stats")
async def get_celery_stats():
    """Get Celery worker statistics"""
    try:
        inspect = celery_app.control.inspect()
        
        # Get active tasks
        active_tasks = inspect.active()
        
        # Get scheduled tasks
        scheduled_tasks = inspect.scheduled()
        
        # Get worker stats
        stats = inspect.stats()
        
        return {
            "active_tasks": active_tasks,
            "scheduled_tasks": scheduled_tasks,
            "worker_stats": stats,
            "timestamp": redis_manager.get_current_ny_time()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
