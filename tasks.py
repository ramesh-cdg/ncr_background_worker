"""
Celery tasks for NCR Upload API with memory management and batch processing
"""
import os
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from celery import current_task, group, chain
from celery.exceptions import Retry, WorkerLostError

from celery_app import celery_app, memory_manager
from database import DatabaseManager
from sftp_client import SFTPManager
from redis_manager import redis_manager
from file_processor import FileProcessor
from validation_service import ValidationService
from models import JobStatus
from config import settings


@celery_app.task(bind=True, name='tasks.process_job_task', autoretry_for=(Exception,), retry_kwargs={'max_retries': 2, 'countdown': 60})
def process_job_task(
    self, 
    job_id: str, 
    username: str, 
    campaign: str, 
    row_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Process a single job with memory management and error handling
    """
    task_id = self.request.id
    
    try:
        # Celery handles concurrency control - no need to check memory here
        # The worker will only pick up tasks when it has capacity
        
        # Update status to processing
        redis_manager.update_job_status(task_id, JobStatus.PROCESSING, "Starting job processing")
        
        # Get file paths from database
        redis_manager.update_job_status(task_id, JobStatus.PROCESSING, "Fetching file paths from database")
        file_paths, sku_id = DatabaseManager.get_file_paths_from_db(job_id)
        
        if not file_paths:
            redis_manager.update_job_status(task_id, JobStatus.FAILED, "No files found for this job")
            return {"status": "failed", "message": "No files found"}
        
        total_files = len(file_paths)
        redis_manager.update_job_status(
            task_id, 
            JobStatus.PROCESSING, 
            f"Found {total_files} files to process",
            {"total_files": total_files, "processed_files": 0, "percentage": 0}
        )
        
        # Get SFTP connection
        sftp, transport = SFTPManager.get_connection()
        
        try:
            # Setup directories
            remote_base_dir = f"{job_id}/"
            SFTPManager.check_and_delete_folder(sftp, remote_base_dir)
            
            download_dir = f"/tmp/validator_files/{job_id}"
            zip_download_dir = f"/tmp/validator_zipfiles/"
            os.makedirs(download_dir, exist_ok=True)
            os.makedirs(zip_download_dir, exist_ok=True)
            
            # Clean structure and prepare files
            redis_manager.update_job_status(task_id, JobStatus.PROCESSING, "Organizing file structure")
            outputs, materials = FileProcessor.clean_structure(file_paths, sku_id)
            
            all_local_files = []
            processed_count = 0
            
            # Download and prepare output files
            for key, val in outputs.items():
                # Light memory check - only fail if memory is critically high
                if memory_manager.get_memory_usage()['system_memory_percent'] > 95:
                    raise Exception("Critical memory usage during file processing")
                
                redis_manager.update_job_status(
                    task_id, 
                    JobStatus.PROCESSING, 
                    f"Downloading file: {os.path.basename(key)}",
                    {
                        "current_file": os.path.basename(key), 
                        "processed_files": processed_count, 
                        "percentage": int((processed_count / total_files) * 100)
                    }
                )
                
                result = FileProcessor.download_and_prepare(val, key, download_dir)
                if result:
                    all_local_files.append(result)
                processed_count += 1
            
            # Download and prepare material files
            for mat_id, textures in materials.items():
                for tex_type, path in textures.items():
                    # Check memory during processing
                    if not memory_manager.is_memory_available():
                        raise Exception("Insufficient memory during material processing")
                    
                    redis_manager.update_job_status(
                        task_id, 
                        JobStatus.PROCESSING, 
                        f"Downloading material: {os.path.basename(path)}",
                        {
                            "current_file": os.path.basename(path), 
                            "processed_files": processed_count, 
                            "percentage": int((processed_count / total_files) * 100)
                        }
                    )
                    
                    result = FileProcessor.download_and_prepare(path, tex_type, download_dir)
                    if result:
                        all_local_files.append(result)
                    processed_count += 1
            
            # Create zip file
            redis_manager.update_job_status(task_id, JobStatus.PROCESSING, "Creating validation package")
            zip_path = os.path.join(zip_download_dir, f"{job_id}.zip")
            FileProcessor.zip_files(zip_path, download_dir)
            
            # Send to validator and update database
            redis_manager.update_job_status(task_id, JobStatus.PROCESSING, "Sending to validator")
            if ValidationService.send_to_validator(zip_path, sku_id, job_id, username, campaign, row_id):
                redis_manager.update_job_status(task_id, JobStatus.VALIDATION_PASSED, "Validation passed, uploading files")
                
                # Upload files
                for i, local_path in enumerate(all_local_files):
                    relative_path = os.path.relpath(local_path, download_dir)
                    remote_path = os.path.join(remote_base_dir, relative_path)
                    
                    redis_manager.update_job_status(
                        task_id, 
                        JobStatus.UPLOADING, 
                        f"Uploading: {os.path.basename(local_path)}",
                        {
                            "current_file": os.path.basename(local_path), 
                            "processed_files": i + 1, 
                            "total_files": len(all_local_files),
                            "percentage": int(((i + 1) / len(all_local_files)) * 100)
                        }
                    )
                    
                    SFTPManager.upload_to_sftp(sftp, local_path, remote_path)
                
                # Cleanup
                FileProcessor.cleanup_files(all_local_files, zip_path, download_dir)
                
                redis_manager.update_job_status(task_id, JobStatus.COMPLETED, "Job completed successfully")
                return {"status": "completed", "message": "Job completed successfully"}
                
            else:
                redis_manager.update_job_status(task_id, JobStatus.VALIDATION_FAILED, "Validation failed, no files uploaded")
                
                # Cleanup on validation failure
                FileProcessor.cleanup_files(all_local_files, zip_path, download_dir)
                return {"status": "validation_failed", "message": "Validation failed"}
        
        finally:
            # Close SFTP connection
            sftp.close()
            transport.close()
    
    except Retry:
        raise
    except Exception as e:
        error_msg = f"Job processing failed: {str(e)}"
        redis_manager.update_job_status(task_id, JobStatus.FAILED, error_msg)
        print(f"Error processing job {job_id}: {e}")
        
        # Schedule cleanup for failed job after 1 hour
        cleanup_failed_job.apply_async(args=[task_id], countdown=3600)
        
        return {"status": "failed", "message": error_msg}


@celery_app.task(bind=True, name='tasks.batch_process_jobs')
def batch_process_jobs(self, job_requests: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Process multiple jobs in batch with memory management
    """
    batch_id = self.request.id
    results = []
    
    try:
        # Check memory before starting batch
        if not memory_manager.is_memory_available():
            raise Retry('Insufficient memory for batch processing', countdown=120, max_retries=2)
        
        # Get recommended concurrency based on available memory
        recommended_concurrency = memory_manager.get_recommended_concurrency()
        batch_size = min(len(job_requests), recommended_concurrency, settings.batch_size)
        
        print(f"Processing batch of {len(job_requests)} jobs with concurrency {batch_size}")
        
        # Create job groups for parallel processing
        job_groups = []
        for i in range(0, len(job_requests), batch_size):
            batch_chunk = job_requests[i:i + batch_size]
            group_tasks = []
            
            for job_req in batch_chunk:
                task = process_job_task.s(
                    job_req['job_id'],
                    job_req['username'],
                    job_req['campaign'],
                    job_req.get('row_id')
                )
                group_tasks.append(task)
            
            job_groups.append(group(*group_tasks))
        
        # Process groups sequentially to manage memory
        for i, job_group in enumerate(job_groups):
            print(f"Processing batch group {i + 1}/{len(job_groups)}")
            
            # Check memory before each group
            if not memory_manager.is_memory_available():
                print("Insufficient memory, waiting before next group")
                import time
                time.sleep(60)
            
            # Execute group
            group_result = job_group.apply_async()
            results.extend(group_result.get())
        
        return {
            "batch_id": batch_id,
            "total_jobs": len(job_requests),
            "processed_jobs": len(results),
            "results": results
        }
        
    except Exception as e:
        error_msg = f"Batch processing failed: {str(e)}"
        print(f"Error in batch processing: {e}")
        return {
            "batch_id": batch_id,
            "status": "failed",
            "message": error_msg,
            "results": results
        }


@celery_app.task(name='tasks.memory_monitor_task')
def memory_monitor_task() -> Dict[str, Any]:
    """
    Monitor memory usage and log statistics
    """
    try:
        memory_stats = memory_manager.get_memory_usage()
        
        # Log memory statistics
        print(f"Memory Stats - Process: {memory_stats['process_memory_mb']:.2f}MB "
              f"({memory_stats['process_memory_percent']:.1f}%), "
              f"System: {memory_stats['system_memory_percent']:.1f}%")
        
        # Check if memory usage is high
        if memory_stats['system_memory_percent'] > settings.max_memory_usage_percent:
            print(f"WARNING: High memory usage detected: {memory_stats['system_memory_percent']:.1f}%")
        
        return {
            "status": "success",
            "memory_stats": memory_stats,
            "recommended_concurrency": memory_manager.get_recommended_concurrency(),
            "can_accept_jobs": memory_manager.should_accept_new_job()
        }
        
    except Exception as e:
        print(f"Error in memory monitoring: {e}")
        return {"status": "error", "message": str(e)}


@celery_app.task(name='tasks.cleanup_failed_job')
def cleanup_failed_job(task_id: str) -> Dict[str, Any]:
    """
    Clean up a specific failed job from Redis
    """
    try:
        job_data = redis_manager.get_job_status(task_id)
        if job_data and job_data["status"] == JobStatus.FAILED:
            redis_manager.client.delete(f"job:{task_id}")
            print(f"Cleaned up failed job: {task_id}")
            return {"status": "success", "task_id": task_id, "message": "Failed job cleaned up"}
        else:
            return {"status": "skipped", "task_id": task_id, "message": "Job not found or not failed"}
    except Exception as e:
        print(f"Error cleaning up failed job {task_id}: {e}")
        return {"status": "error", "task_id": task_id, "message": str(e)}


@celery_app.task(name='tasks.cleanup_old_jobs')
def cleanup_old_jobs() -> Dict[str, Any]:
    """
    Clean up old completed/failed jobs from Redis
    """
    try:
        cleaned_count = 0
        failed_count = 0
        current_time = redis_manager.get_current_ny_time()
        
        # Get all job keys
        for key in redis_manager.client.scan_iter("job:*"):
            task_id = key.split(":")[1]
            job_data = redis_manager.get_job_status(task_id)
            
            if job_data:
                # Check if job is old and completed/failed
                try:
                    job_timestamp = datetime.fromisoformat(job_data["timestamp"])
                    time_diff = (current_time - job_timestamp).total_seconds()
                    
                    # Clean up jobs older than configured hours
                    if time_diff > settings.job_expire_hours * 3600:
                        if job_data["status"] in [JobStatus.COMPLETED, JobStatus.FAILED]:
                            redis_manager.client.delete(key)
                            cleaned_count += 1
                            if job_data["status"] == JobStatus.FAILED:
                                failed_count += 1
                        elif job_data["status"] == JobStatus.PENDING:
                            # Clean up very old pending jobs (older than 24 hours)
                            if time_diff > 24 * 3600:
                                redis_manager.client.delete(key)
                                cleaned_count += 1
                                print(f"Cleaned up stale pending job: {task_id}")
                except Exception as e:
                    print(f"Error processing job {task_id}: {e}")
                    # If we can't parse the timestamp, clean it up
                    redis_manager.client.delete(key)
                    cleaned_count += 1
        
        print(f"Cleaned up {cleaned_count} old jobs ({failed_count} failed)")
        return {"status": "success", "cleaned_count": cleaned_count, "failed_count": failed_count}
        
    except Exception as e:
        print(f"Error cleaning up old jobs: {e}")
        return {"status": "error", "message": str(e)}


@celery_app.task(name='tasks.health_check_task')
def health_check_task() -> Dict[str, Any]:
    """
    Perform health check on all system components
    """
    try:
        health_status = {
            "redis": "healthy" if redis_manager.test_connection() else "unhealthy",
            "database": "healthy",
            "memory": "healthy" if memory_manager.is_memory_available() else "unhealthy",
            "timestamp": redis_manager.get_current_ny_time().isoformat()
        }
        
        # Test database connection
        try:
            conn = DatabaseManager.get_connection()
            conn.close()
        except Exception:
            health_status["database"] = "unhealthy"
        
        overall_status = "healthy" if all(
            status == "healthy" for status in health_status.values() 
            if isinstance(status, str) and status in ["healthy", "unhealthy"]
        ) else "degraded"
        
        health_status["overall"] = overall_status
        return health_status
        
    except Exception as e:
        return {"status": "error", "message": str(e)}
