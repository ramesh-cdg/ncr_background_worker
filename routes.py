"""
API routes module - Simplified
"""
import os
from datetime import datetime
from fastapi import APIRouter, HTTPException
from typing import Optional, List, Dict, Any
from pydantic import BaseModel

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
class BatchJobRequest(BaseModel):
    """Request model for batch job processing"""
    job_id: str
    username: str
    campaign: str
    row_id: Optional[int] = None


class RedisResetRequest(BaseModel):
    """Request model for Redis reset"""
    password: str


@router.get("/")
async def root():
    """Root endpoint"""
    return {"message": "NCR Upload API is running", "version": settings.api_version}


@router.post("/process-job", response_model=JobResponse)
async def process_job(job_request: JobRequest):
    """Process a single job by job_id"""
    try:
        # Start Celery task
        celery_result = process_job_task.delay(
            job_request.job_id,
            job_request.username,
            job_request.campaign,
            job_request.row_id
        )
        
        # Use the Celery task ID as the primary task ID
        task_id = celery_result.id
        
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
            message="Job processing started",
            timestamp=redis_manager.get_current_ny_time(),
            task_id=task_id
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/job-status/{job_id}")
async def get_job_status(job_id: str):
    """Get status of a specific job by job_id"""
    try:
        print(f"🔍 [API] Looking up job: {job_id}")
        
        # Find the task for this job_id
        matching_jobs = redis_manager.get_jobs_by_job_id(job_id)
        
        if not matching_jobs:
            raise HTTPException(status_code=404, detail=f"No job found with job_id: {job_id}")
        
        # Get the first matching job (should be only one since we don't keep historical data)
        job = matching_jobs[0]
        
        # Only return if job is in progress or completed
        in_progress_statuses = ["pending", "processing", "completed"]
        if job.get("status") not in in_progress_statuses:
            raise HTTPException(status_code=404, detail=f"Job {job_id} is not found (status: {job.get('status')})")
        
        print(f"✅ [API] Found in-progress job for job_id {job_id}")
        
        return {
            "job_id": job_id,
            "username": job.get("username", ""),
            "task_id": job["task_id"],
            "celery_task_id": job.get("celery_task_id", ""),
            "status": job["status"],
            "progress": job.get("progress", {}),
            "message": job.get("message", ""),
            "campaign": job.get("campaign", ""),
            "row_id": job.get("row_id", ""),
            "timestamp": job.get("timestamp", ""),
            "logs": job.get("logs", [])
        }
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [API] Error looking up job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/running-tasks")
async def get_running_tasks():
    """Get list of all running tasks"""
    try:
        # Get all active jobs from Redis
        active_jobs = redis_manager.get_active_jobs()
        
        # Filter to only in-progress and completed jobs
        in_progress_jobs = [
            job for job in active_jobs 
            if job.get("status") in ["pending", "processing", "completed"]
        ]
        
        return {
            "running_tasks": in_progress_jobs,
            "count": len(in_progress_jobs),
            "timestamp": redis_manager.get_current_ny_time()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/process-batch")
async def process_batch_jobs_endpoint(
    job_requests: List[BatchJobRequest], 
    common_username: Optional[str] = None
):
    """Process multiple jobs in batch"""
    try:
        # Check memory availability
        if not memory_manager.should_accept_new_job():
            raise HTTPException(
                status_code=503, 
                detail="Server memory usage is high. Please try again later."
            )
        
        # Auto-select common username if not provided (use first username)
        if not common_username and job_requests:
            common_username = job_requests[0].username
            print(f"🔄 [API] Auto-selected common username: {common_username}")
        
        # Convert to batch format
        batch_jobs = []
        for job_req in job_requests:
            # Use the common username for all jobs
            batch_jobs.append({
                "job_id": job_req.job_id,
                "username": common_username,
                "campaign": job_req.campaign,
                "row_id": job_req.row_id
            })
        
        # Start batch processing
        batch_result = batch_process_jobs.delay(batch_jobs)
        
        # Store batch info in Redis for tracking (using common_username as key)
        batch_info = {
            "batch_id": batch_result.id,
            "total_jobs": len(job_requests),
            "common_username": common_username,
            "status": "processing",
            "created_at": redis_manager.get_current_ny_time().isoformat(),
            "job_ids": [job_req.job_id for job_req in job_requests]
        }
        
        # Store batch info in Redis with username as key
        redis_manager.client.hset(f"batch:{common_username}", mapping={
            "batch_id": batch_result.id,
            "total_jobs": str(len(job_requests)),
            "common_username": common_username or "",
            "status": "processing",
            "created_at": batch_info["created_at"],
            "job_ids": ",".join(batch_info["job_ids"])
        })
        redis_manager.client.expire(f"batch:{common_username}", 86400)  # Expire in 24 hours
        
        return {
            "batch_id": batch_result.id,
            "total_jobs": len(job_requests),
            "common_username": common_username,
            "status": "processing",
            "message": f"Batch processing started for {len(job_requests)} jobs with username '{common_username}'",
            "timestamp": redis_manager.get_current_ny_time()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/batch-status/{username}")
async def get_batch_status(username: str):
    """Get batch processing status by username"""
    try:
        print(f"🔍 [API] Getting batch status for username: {username}")
        
        # Get batch info from Redis
        batch_data = redis_manager.client.hgetall(f"batch:{username}")
        if not batch_data:
            raise HTTPException(status_code=404, detail=f"No batch found for username: {username}")
        
        batch_id = batch_data.get("batch_id")
        if not batch_id:
            raise HTTPException(status_code=404, detail=f"Invalid batch data for username: {username}")
        
        # Get current batch status from Celery
        from celery.result import AsyncResult
        result = AsyncResult(batch_id, app=celery_app)
        
        if result.ready():
            if result.successful():
                batch_status = "completed"
                batch_result = result.result
            else:
                batch_status = "failed"
                batch_result = str(result.result)
        else:
            batch_status = "processing"
            batch_result = None
        
        # Get individual job results
        individual_results = []
        if batch_result and "job_results" in batch_result:
            for job in batch_result["job_results"]:
                task_id = job.get("task_id")
                if task_id:
                    try:
                        task_result = AsyncResult(task_id, app=celery_app)
                        if task_result.ready():
                            individual_results.append({
                                "job_id": job.get("job_id"),
                                "task_id": task_id,
                                "status": "completed" if task_result.successful() else "failed",
                                "result": task_result.result if task_result.successful() else str(task_result.result)
                            })
                        else:
                            individual_results.append({
                                "job_id": job.get("job_id"),
                                "task_id": task_id,
                                "status": "processing",
                                "result": None
                            })
                    except Exception as e:
                        individual_results.append({
                            "job_id": job.get("job_id"),
                            "task_id": task_id,
                            "status": "error",
                            "result": str(e)
                        })
        
        return {
            "username": username,
            "batch_id": batch_id,
            "status": batch_status,
            "total_jobs": int(batch_data.get("total_jobs", 0)),
            "created_at": batch_data.get("created_at", ""),
            "individual_results": individual_results,
            "completed_jobs": len([r for r in individual_results if r["status"] == "completed"]),
            "failed_jobs": len([r for r in individual_results if r["status"] == "failed"]),
            "processing_jobs": len([r for r in individual_results if r["status"] == "processing"]),
            "timestamp": redis_manager.get_current_ny_time()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [API] Error getting batch status for username {username}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
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
        
        # Get registered tasks
        registered_tasks = inspect.registered()
        
        return {
            "active_tasks": active_tasks,
            "scheduled_tasks": scheduled_tasks,
            "worker_stats": stats,
            "registered_tasks": registered_tasks,
            "timestamp": redis_manager.get_current_ny_time()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/redis-stats")
async def get_redis_stats():
    """Get Redis statistics and job counts"""
    try:
        # Get Redis info
        redis_info = redis_manager.client.info()
        
        # Count jobs by status
        job_counts = {
            "total": 0,
            "pending": 0,
            "processing": 0,
            "completed": 0,
            "failed": 0
        }
        
        for key in redis_manager.client.scan_iter("job:*"):
            task_id = key.split(":")[1]
            job_data = redis_manager.get_job_status(task_id)
            if job_data:
                job_counts["total"] += 1
                status = job_data.get("status", "unknown")
                if status in job_counts:
                    job_counts[status] += 1
        
        return {
            "redis_info": {
                "used_memory": redis_info.get("used_memory_human"),
                "connected_clients": redis_info.get("connected_clients"),
                "total_commands_processed": redis_info.get("total_commands_processed"),
                "keyspace_hits": redis_info.get("keyspace_hits"),
                "keyspace_misses": redis_info.get("keyspace_misses"),
            },
            "job_counts": job_counts,
            "timestamp": redis_manager.get_current_ny_time()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/redis/reset")
async def reset_redis_data(reset_request: RedisResetRequest):
    """Reset all Redis data with password protection"""
    try:
        # Check password
        if reset_request.password != "reset@2025":
            raise HTTPException(status_code=401, detail="Invalid password")
        
        print("🗑️ [API] Redis reset requested - clearing all data...")
        
        # Get all Redis keys
        all_keys = list(redis_manager.client.scan_iter("*"))
        keys_count = len(all_keys)
        
        if keys_count > 0:
            # Delete all keys
            redis_manager.client.delete(*all_keys)
            print(f"✅ [API] Deleted {keys_count} Redis keys")
        else:
            print("ℹ️ [API] No Redis keys found to delete")
        
        return {
            "status": "success",
            "message": f"Redis data reset successfully - deleted {keys_count} keys",
            "deleted_keys": keys_count,
            "timestamp": redis_manager.get_current_ny_time()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [API] Error resetting Redis data: {e}")
        raise HTTPException(status_code=500, detail=str(e))