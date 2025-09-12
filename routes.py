"""
API routes module - Simplified
"""
import os
import tempfile
import shutil
from datetime import datetime
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from typing import Optional, List, Dict, Any
from pydantic import BaseModel

from models import (
    JobRequest, JobResponse, JobStatusResponse, 
    HealthResponse, ActiveJobsResponse, JobStatus,
    FileUploadRequest, FileUploadResponse, FileUploadStatusResponse
)
from database import DatabaseManager
from redis_manager import redis_manager
from celery_app import celery_app, memory_manager
from tasks import process_job_task, batch_process_jobs, health_check_task, process_file_upload_task
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
        
        # Only return if job is in progress
        in_progress_statuses = ["pending", "processing"]
        if job.get("status") not in in_progress_statuses:
            raise HTTPException(status_code=404, detail=f"Job {job_id} is not in progress (status: {job.get('status')})")
        
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
        
        # Filter to only in-progress jobs
        in_progress_jobs = [
            job for job in active_jobs 
            if job.get("status") in ["pending", "processing"]
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
    """Get batch processing status by username with real-time individual task updates"""
    try:
        print(f"🔍 [API] Getting batch status for username: {username}")
        
        # Get batch info from Redis
        batch_data = redis_manager.client.hgetall(f"batch:{username}")
        if not batch_data:
            raise HTTPException(status_code=404, detail=f"No batch found for username: {username}")
        
        batch_id = batch_data.get("batch_id")
        if not batch_id:
            raise HTTPException(status_code=404, detail=f"Invalid batch data for username: {username}")
        
        # Get job IDs from batch data
        job_ids_str = batch_data.get("job_ids", "")
        job_ids = [job_id.strip() for job_id in job_ids_str.split(",") if job_id.strip()]
        
        print(f"📋 [BATCH] Processing {len(job_ids)} job IDs: {job_ids}")
        
        # Get real-time status for each individual job
        individual_results = []
        completed_job_ids = []
        
        for job_id in job_ids:
            print(f"🔍 [BATCH] Checking status for job_id: {job_id}")
            
            # First check Redis for real-time status (if job is still in progress)
            redis_jobs = redis_manager.get_jobs_by_job_id(job_id)
            
            if redis_jobs:
                # Job is still in Redis (in progress)
                job = redis_jobs[0]  # Get the first (and should be only) job
                individual_results.append({
                    "job_id": job_id,
                    "task_id": job.get("task_id", ""),
                    "status": job.get("status", "unknown"),
                    "message": job.get("message", ""),
                    "progress": job.get("progress", {}),
                    "timestamp": job.get("timestamp", "")
                })
                print(f"   ✅ Found in Redis - Status: {job.get('status')}")
            else:
                # Job not in Redis (completed/failed) - check Celery result
                print(f"   🔍 Not in Redis, checking Celery result...")
                
                # Get batch result to find individual task results
                from celery.result import AsyncResult
                batch_result = AsyncResult(batch_id, app=celery_app)
                
                if batch_result.ready() and batch_result.successful():
                    batch_data_result = batch_result.result
                    if "job_results" in batch_data_result:
                        # Find this job in the batch results
                        job_found = False
                        for job_result in batch_data_result["job_results"]:
                            if job_result.get("job_id") == job_id:
                                task_id = job_result.get("task_id")
                                if task_id:
                                    try:
                                        task_result = AsyncResult(task_id, app=celery_app)
                                        if task_result.ready():
                                            status = "completed" if task_result.successful() else "failed"
                                            individual_results.append({
                                                "job_id": job_id,
                                                "task_id": task_id,
                                                "status": status,
                                                "message": f"Job {status}",
                                                "result": task_result.result if task_result.successful() else str(task_result.result),
                                                "timestamp": redis_manager.get_current_ny_time().isoformat()
                                            })
                                            completed_job_ids.append(job_id)
                                            print(f"   ✅ Found in Celery result - Status: {status}")
                                            job_found = True
                                            break
                                    except Exception as e:
                                        print(f"   ❌ Error checking Celery result: {e}")
                                        individual_results.append({
                                            "job_id": job_id,
                                            "task_id": "",
                                            "status": "error",
                                            "message": f"Error checking result: {str(e)}",
                                            "timestamp": redis_manager.get_current_ny_time().isoformat()
                                        })
                                        job_found = True
                                        break
                        
                        if not job_found:
                            # Job not found in batch results - assume completed
                            individual_results.append({
                                "job_id": job_id,
                                "task_id": "",
                                "status": "completed",
                                "message": "Job completed (not found in batch results)",
                                "timestamp": redis_manager.get_current_ny_time().isoformat()
                            })
                            completed_job_ids.append(job_id)
                            print(f"   ✅ Assumed completed (not in batch results)")
                    else:
                        # No job results in batch - assume all completed
                        individual_results.append({
                            "job_id": job_id,
                            "task_id": "",
                            "status": "completed",
                            "message": "Job completed (batch finished)",
                            "timestamp": redis_manager.get_current_ny_time().isoformat()
                        })
                        completed_job_ids.append(job_id)
                        print(f"   ✅ Assumed completed (batch finished)")
                else:
                    # Batch not ready yet, but job not in Redis - this shouldn't happen
                    individual_results.append({
                        "job_id": job_id,
                        "task_id": "",
                        "status": "unknown",
                        "message": "Job status unknown",
                        "timestamp": redis_manager.get_current_ny_time().isoformat()
                    })
                    print(f"   ❓ Status unknown")
        
        # Clean up completed jobs from batch tracking
        if completed_job_ids:
            # Remove completed job IDs from batch tracking
            remaining_job_ids = [job_id for job_id in job_ids if job_id not in completed_job_ids]
            redis_manager.client.hset(f"batch:{username}", "job_ids", ",".join(remaining_job_ids))
            print(f"🧹 [BATCH] Removed completed jobs from batch tracking: {completed_job_ids}")
        
        # Determine overall batch status
        batch_status = "processing"
        if not any(r["status"] in ["pending", "processing"] for r in individual_results):
            batch_status = "completed"
            # Remove batch from Redis when all jobs are done
            redis_manager.client.delete(f"batch:{username}")
            print(f"🗑️ [BATCH] All jobs completed - removed batch from Redis")
        
        return {
            "username": username,
            "batch_id": batch_id,
            "status": batch_status,
            "total_jobs": int(batch_data.get("total_jobs", 0)),
            "created_at": batch_data.get("created_at", ""),
            "individual_results": individual_results,
            "completed_jobs": len([r for r in individual_results if r["status"] == "completed"]),
            "failed_jobs": len([r for r in individual_results if r["status"] == "failed"]),
            "processing_jobs": len([r for r in individual_results if r["status"] in ["pending", "processing"]]),
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


@router.post("/file-upload", response_model=FileUploadResponse)
async def process_file_upload(
    job_id: str = Form(...),
    row_id: Optional[int] = Form(None),
    delivery_file: Optional[UploadFile] = File(None),
    usdz_file: Optional[UploadFile] = File(None),
    glb_file: Optional[UploadFile] = File(None)
):
    """Process file upload with delivery files, USDZ files, and GLB files"""
    try:
        print(f"📤 [API] File upload request received for job_id: {job_id}")
        print(f"   - Row ID: {row_id}")
        print(f"   - Delivery file: {delivery_file.filename if delivery_file else 'None'}")
        print(f"   - USDZ file: {usdz_file.filename if usdz_file else 'None'}")
        print(f"   - GLB file: {glb_file.filename if glb_file else 'None'}")
        
        # Check if any files were provided
        if not any([delivery_file, usdz_file, glb_file]):
            raise HTTPException(status_code=400, detail="No files provided for upload")
        
        # Save uploaded files to temporary locations
        temp_files = {}
        
        try:
            # Save delivery file
            if delivery_file:
                temp_delivery = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
                content = await delivery_file.read()
                temp_delivery.write(content)
                temp_delivery.close()
                temp_files['delivery'] = temp_delivery.name
                print(f"   ✅ Delivery file saved to: {temp_delivery.name}")
            
            # Save USDZ file
            if usdz_file:
                temp_usdz = tempfile.NamedTemporaryFile(delete=False, suffix='.usdz')
                content = await usdz_file.read()
                temp_usdz.write(content)
                temp_usdz.close()
                temp_files['usdz'] = temp_usdz.name
                print(f"   ✅ USDZ file saved to: {temp_usdz.name}")
            
            # Save GLB file
            if glb_file:
                temp_glb = tempfile.NamedTemporaryFile(delete=False, suffix='.glb')
                content = await glb_file.read()
                temp_glb.write(content)
                temp_glb.close()
                temp_files['glb'] = temp_glb.name
                print(f"   ✅ GLB file saved to: {temp_glb.name}")
            
            # Start Celery task
            celery_result = process_file_upload_task.delay(
                job_id=job_id,
                row_id=row_id,
                delivery_file_path=temp_files.get('delivery'),
                usdz_file_path=temp_files.get('usdz'),
                glb_file_path=temp_files.get('glb')
            )
            
            # Use the Celery task ID as the primary task ID
            task_id = celery_result.id
            
            # Create job status in Redis with Celery task ID
            redis_manager.create_job_status(
                job_id, 
                task_id, 
                "system",  # username for file uploads
                "FILE_UPLOAD",  # campaign for file uploads
                row_id,
                celery_task_id=celery_result.id
            )
            
            return FileUploadResponse(
                job_id=job_id,
                status="processing",
                message="File upload processing started",
                timestamp=redis_manager.get_current_ny_time(),
                task_id=task_id
            )
            
        finally:
            # Clean up temporary files after task is started
            for temp_file in temp_files.values():
                try:
                    os.unlink(temp_file)
                    print(f"   🧹 Cleaned up temp file: {temp_file}")
                except Exception as e:
                    print(f"   ⚠️ Failed to clean up temp file {temp_file}: {e}")
        
    except Exception as e:
        print(f"❌ [API] Error in file upload: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/file-upload-status/{job_id}")
async def get_file_upload_status(job_id: str):
    """Get status of a specific file upload job by job_id"""
    try:
        print(f"🔍 [API] Looking up file upload job: {job_id}")
        
        # Find the task for this job_id
        matching_jobs = redis_manager.get_jobs_by_job_id(job_id)
        
        if not matching_jobs:
            raise HTTPException(status_code=404, detail=f"No file upload job found with job_id: {job_id}")
        
        # Get the first matching job (should be only one since we don't keep historical data)
        job = matching_jobs[0]
        
        # Only return if job is in progress
        in_progress_statuses = ["file_upload_pending", "file_upload_processing"]
        if job.get("status") not in in_progress_statuses:
            raise HTTPException(status_code=404, detail=f"File upload job {job_id} is not in progress (status: {job.get('status')})")
        
        print(f"✅ [API] Found in-progress file upload job for job_id {job_id}")
        
        return {
            "job_id": job_id,
            "task_id": job["task_id"],
            "celery_task_id": job.get("celery_task_id", ""),
            "status": job["status"],
            "progress": job.get("progress", {}),
            "message": job.get("message", ""),
            "timestamp": job.get("timestamp", ""),
            "logs": job.get("logs", [])
        }
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [API] Error looking up file upload job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))