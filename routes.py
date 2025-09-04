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


@router.get("/job-status-by-job-id/{job_id}")
async def get_job_status_by_job_id(job_id: str):
    """Get the status of a job by job ID (returns latest task)"""
    try:
        print(f"🔍 [API] Looking up job by job_id: {job_id}")
        
        # Find all tasks for this job_id
        matching_jobs = redis_manager.get_jobs_by_job_id(job_id)
        
        if not matching_jobs:
            raise HTTPException(status_code=404, detail=f"No jobs found with job_id: {job_id}")
        
        # Sort by timestamp to get the latest one
        latest_job = max(matching_jobs, key=lambda x: x.get("timestamp", ""))
        
        print(f"✅ [API] Found {len(matching_jobs)} jobs for job_id {job_id}, returning latest")
        
        return {
            "job_id": job_id,
            "task_id": latest_job["task_id"],
            "celery_task_id": latest_job.get("celery_task_id", ""),
            "status": latest_job["status"],
            "progress": latest_job.get("progress", {}),
            "message": latest_job.get("message", ""),
            "username": latest_job.get("username", ""),
            "campaign": latest_job.get("campaign", ""),
            "row_id": latest_job.get("row_id", ""),
            "timestamp": latest_job.get("timestamp", ""),
            "logs": latest_job.get("logs", []),
            "total_tasks_for_job": len(matching_jobs),
            "all_tasks": [
                {
                    "task_id": job["task_id"],
                    "status": job["status"],
                    "timestamp": job.get("timestamp", ""),
                    "message": job.get("message", "")
                }
                for job in matching_jobs
            ]
        }
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [API] Error looking up job {job_id}: {e}")
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


@router.get("/job-history/{job_id}")
async def get_job_history(job_id: str):
    """Get complete history of all tasks for a specific job_id"""
    try:
        print(f"🔍 [API] Getting job history for job_id: {job_id}")
        
        # Find all tasks for this job_id
        all_jobs = redis_manager.get_jobs_by_job_id(job_id)
        
        if not all_jobs:
            raise HTTPException(status_code=404, detail=f"No jobs found with job_id: {job_id}")
        
        # Sort by timestamp (oldest first)
        sorted_jobs = sorted(all_jobs, key=lambda x: x.get("timestamp", ""))
        
        # Get the latest job for current status
        latest_job = sorted_jobs[-1] if sorted_jobs else None
        
        print(f"✅ [API] Found {len(all_jobs)} tasks for job_id {job_id}")
        
        return {
            "job_id": job_id,
            "total_tasks": len(all_jobs),
            "current_status": latest_job["status"] if latest_job else "unknown",
            "latest_task_id": latest_job["task_id"] if latest_job else None,
            "latest_message": latest_job.get("message", "") if latest_job else "",
            "latest_timestamp": latest_job.get("timestamp", "") if latest_job else "",
            "username": latest_job.get("username", "") if latest_job else "",
            "campaign": latest_job.get("campaign", "") if latest_job else "",
            "row_id": latest_job.get("row_id", "") if latest_job else "",
            "task_history": [
                {
                    "task_id": job["task_id"],
                    "celery_task_id": job.get("celery_task_id", ""),
                    "status": job["status"],
                    "message": job.get("message", ""),
                    "timestamp": job.get("timestamp", ""),
                    "progress": job.get("progress", {}),
                    "logs": job.get("logs", [])
                }
                for job in sorted_jobs
            ],
            "status_summary": {
                "pending": len([j for j in all_jobs if j["status"] == "pending"]),
                "processing": len([j for j in all_jobs if j["status"] == "processing"]),
                "completed": len([j for j in all_jobs if j["status"] == "completed"]),
                "failed": len([j for j in all_jobs if j["status"] == "failed"]),
                "validation_passed": len([j for j in all_jobs if j["status"] == "validation_passed"]),
                "validation_failed": len([j for j in all_jobs if j["status"] == "validation_failed"]),
                "uploading": len([j for j in all_jobs if j["status"] == "uploading"])
            }
        }
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [API] Error getting job history for {job_id}: {e}")
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
async def get_active_jobs(username: Optional[str] = None, campaign: Optional[str] = None):
    """Get active jobs from Redis with optional filtering by username and/or campaign"""
    try:
        active_jobs = redis_manager.get_active_jobs(username=username, campaign=campaign)
        return ActiveJobsResponse(active_jobs=active_jobs, count=len(active_jobs))
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs")
async def get_jobs(
    username: Optional[str] = None, 
    campaign: Optional[str] = None,
    status: Optional[str] = None,
    limit: Optional[int] = 100
):
    """Get jobs from Redis with filtering options"""
    try:
        jobs = redis_manager.get_jobs(
            username=username, 
            campaign=campaign, 
            status=status, 
            limit=limit
        )
        
        return {
            "jobs": jobs,
            "count": len(jobs),
            "filters": {
                "username": username,
                "campaign": campaign,
                "status": status,
                "limit": limit
            },
            "timestamp": redis_manager.get_current_ny_time()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/process-batch")
async def process_batch_jobs(
    job_requests: List[JobRequest], 
    common_username: Optional[str] = None
):
    """Process multiple jobs in batch with memory management and automatic common username"""
    try:
        # Check memory availability
        if not memory_manager.should_accept_new_job():
            raise HTTPException(
                status_code=503, 
                detail="Server memory usage is high. Please try again later."
            )
        
        # Auto-select common username if not provided
        if not common_username and job_requests:
            # Use the first username as the common username
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
        
        # Store batch info in Redis for tracking
        batch_info = {
            "batch_id": batch_result.id,
            "total_jobs": len(job_requests),
            "common_username": common_username,
            "status": "processing",
            "created_at": redis_manager.get_current_ny_time().isoformat(),
            "job_ids": [job_req.job_id for job_req in job_requests]
        }
        
        # Store batch info in Redis
        redis_manager.client.hset(f"batch:{batch_result.id}", mapping={
            "batch_id": batch_result.id,
            "total_jobs": str(len(job_requests)),
            "common_username": common_username or "",
            "status": "processing",
            "created_at": batch_info["created_at"],
            "job_ids": ",".join(batch_info["job_ids"])
        })
        redis_manager.client.expire(f"batch:{batch_result.id}", 86400)  # Expire in 24 hours
        
        return {
            "batch_id": batch_result.id,
            "total_jobs": len(job_requests),
            "common_username": common_username,
            "status": "processing",
            "message": f"Batch processing started for {len(job_requests)} jobs with common username '{common_username}'",
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
                batch_result = result.result
                
                # Get individual task results
                individual_results = []
                if "job_results" in batch_result:
                    for job in batch_result["job_results"]:
                        task_id = job.get("task_id")
                        job_id = job.get("job_id")
                        try:
                            task_result = AsyncResult(task_id, app=celery_app)
                            if task_result.ready():
                                individual_results.append({
                                    "job_id": job_id,
                                    "task_id": task_id,
                                    "status": "completed" if task_result.successful() else "failed",
                                    "result": task_result.result if task_result.successful() else str(task_result.result)
                                })
                            else:
                                individual_results.append({
                                    "job_id": job_id,
                                    "task_id": task_id,
                                    "status": "processing",
                                    "result": None
                                })
                        except Exception as e:
                            individual_results.append({
                                "job_id": job_id,
                                "task_id": task_id,
                                "status": "error",
                                "result": str(e)
                            })
                
                return {
                    "batch_id": batch_id,
                    "status": "completed",
                    "batch_result": batch_result,
                    "individual_results": individual_results,
                    "completed_tasks": len([r for r in individual_results if r["status"] == "completed"]),
                    "failed_tasks": len([r for r in individual_results if r["status"] == "failed"]),
                    "processing_tasks": len([r for r in individual_results if r["status"] == "processing"]),
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


@router.get("/batch-status-by-username/{username}")
async def get_batch_status_by_username(username: str):
    """Get batch processing status by username"""
    try:
        print(f"🔍 [API] Getting batch status for username: {username}")
        
        # Find all batches for this username
        batches = redis_manager.get_batches_by_username(username)
        
        if not batches:
            return {
                "username": username,
                "total_batches": 0,
                "batches": [],
                "summary": {
                    "processing": 0,
                    "completed": 0,
                    "failed": 0
                },
                "message": f"No batches found for username: {username}",
                "timestamp": redis_manager.get_current_ny_time()
            }
        
        # Get detailed status for each batch
        batch_details = []
        for batch in batches:
            batch_id = batch["batch_id"]
            
            # Get current batch status from Celery
            try:
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
                
                batch_details.append({
                    "batch_id": batch_id,
                    "status": batch_status,
                    "total_jobs": batch.get("total_jobs", 0),
                    "created_at": batch.get("created_at", ""),
                    "individual_results": individual_results,
                    "completed_jobs": len([r for r in individual_results if r["status"] == "completed"]),
                    "failed_jobs": len([r for r in individual_results if r["status"] == "failed"]),
                    "processing_jobs": len([r for r in individual_results if r["status"] == "processing"])
                })
                
            except Exception as e:
                print(f"❌ [API] Error getting batch status for {batch_id}: {e}")
                batch_details.append({
                    "batch_id": batch_id,
                    "status": "error",
                    "total_jobs": batch.get("total_jobs", 0),
                    "created_at": batch.get("created_at", ""),
                    "error": str(e)
                })
        
        # Calculate summary
        summary = {
            "processing": len([b for b in batch_details if b["status"] == "processing"]),
            "completed": len([b for b in batch_details if b["status"] == "completed"]),
            "failed": len([b for b in batch_details if b["status"] == "failed"])
        }
        
        print(f"✅ [API] Found {len(batches)} batches for username {username}")
        
        return {
            "username": username,
            "total_batches": len(batches),
            "batches": batch_details,
            "summary": summary,
            "timestamp": redis_manager.get_current_ny_time()
        }
        
    except Exception as e:
        print(f"❌ [API] Error getting batch status for username {username}: {e}")
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


@router.post("/cleanup-failed-jobs")
async def cleanup_failed_jobs():
    """Manually trigger cleanup of failed jobs"""
    try:
        from tasks import cleanup_old_jobs
        
        # Run cleanup task
        result = cleanup_old_jobs.delay()
        cleanup_result = result.get(timeout=30)
        
        return {
            "status": "success",
            "message": "Cleanup task completed",
            "result": cleanup_result,
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
            "failed": 0,
            "validation_passed": 0,
            "validation_failed": 0,
            "uploading": 0
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
