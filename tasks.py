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
        redis_manager.update_job_status(task_id, JobStatus.PROCESSING, "Initializing job processing")
        
        # Get file paths from database
        redis_manager.update_job_status(task_id, JobStatus.PROCESSING, "Querying database for file paths")
        print(f"🔍 [TASK {task_id}] Fetching file paths for job_id: {job_id}")
        
        file_paths, sku_id = DatabaseManager.get_file_paths_from_db(job_id)
        
        print(f"📊 [TASK {task_id}] Database query results:")
        print(f"   - Job ID: {job_id}")
        print(f"   - SKU ID: {sku_id}")
        print(f"   - File paths count: {len(file_paths) if file_paths else 0}")
        
        if file_paths:
            print(f"   - File paths (first 10):")
            for i, path in enumerate(file_paths[:10]):
                print(f"     {i+1}. {path}")
            if len(file_paths) > 10:
                print(f"     ... and {len(file_paths) - 10} more files")
        else:
            print("   - No file paths returned from database")
        
        if not file_paths:
            error_msg = f"No files found for job_id: {job_id}, sku_id: {sku_id}"
            print(f"❌ [TASK {task_id}] {error_msg}")
            redis_manager.update_job_status(task_id, JobStatus.FAILED, error_msg)
            return {"status": "failed", "message": "No files found"}
        
        total_files = len(file_paths)
        redis_manager.update_job_status(
            task_id, 
            JobStatus.PROCESSING, 
            f"Found {total_files} files to process",
            {"total_files": total_files, "processed_files": 0, "percentage": 0}
        )
        
        # Get SFTP connection
        redis_manager.update_job_status(task_id, JobStatus.PROCESSING, "Establishing SFTP connection")
        print(f"🔗 [TASK {task_id}] Getting SFTP connection...")
        sftp, transport = SFTPManager.get_connection()
        print(f"✅ [TASK {task_id}] SFTP connection established")
        
        try:
            # Setup directories
            remote_base_dir = f"{job_id}/"
            print(f"📁 [TASK {task_id}] Setting up directories:")
            print(f"   - Remote base dir: {remote_base_dir}")
            
            SFTPManager.check_and_delete_folder(sftp, remote_base_dir)
            
            download_dir = f"/tmp/validator_files/{job_id}"
            zip_download_dir = f"/tmp/validator_zipfiles/"
            print(f"   - Download dir: {download_dir}")
            print(f"   - Zip dir: {zip_download_dir}")
            
            os.makedirs(download_dir, exist_ok=True)
            os.makedirs(zip_download_dir, exist_ok=True)
            print(f"✅ [TASK {task_id}] Directories created successfully")
            
            # Clean structure and prepare files
            redis_manager.update_job_status(task_id, JobStatus.PROCESSING, "Organizing file structure and grouping materials")
            print(f"🔧 [TASK {task_id}] Organizing file structure for {len(file_paths)} files...")
            outputs, materials = FileProcessor.clean_structure(file_paths, sku_id)
            
            print(f"📋 [TASK {task_id}] File structure organization results:")
            print(f"   - Output files count: {len(outputs)}")
            print(f"   - Material groups count: {len(materials)}")
            
            if outputs:
                print(f"   - Output files (first 5):")
                for i, (key, val) in enumerate(list(outputs.items())[:5]):
                    print(f"     {i+1}. {key} -> {val}")
                if len(outputs) > 5:
                    print(f"     ... and {len(outputs) - 5} more output files")
            
            if materials:
                print(f"   - Material groups:")
                for mat_id, textures in materials.items():
                    print(f"     Material {mat_id}: {len(textures)} textures")
                    for tex_type, path in list(textures.items())[:3]:  # Show first 3
                        print(f"       - {tex_type} -> {path}")
                    if len(textures) > 3:
                        print(f"       ... and {len(textures) - 3} more textures")
            
            all_local_files = []
            processed_count = 0
            
            # Download and prepare output files
            redis_manager.update_job_status(task_id, JobStatus.PROCESSING, f"Downloading {len(outputs)} output files from Wasabi")
            print(f"⬇️ [TASK {task_id}] Starting download of {len(outputs)} output files...")
            for key, val in outputs.items():
                # Light memory check - only fail if memory is critically high
                memory_usage = memory_manager.get_memory_usage()
                if memory_usage['system_memory_percent'] > 95:
                    raise Exception(f"Critical memory usage: {memory_usage['system_memory_percent']:.1f}%")
                
                print(f"📥 [TASK {task_id}] Downloading output file {processed_count + 1}/{len(outputs)}:")
                print(f"   - Source: {key}")
                print(f"   - Target: {val}")
                print(f"   - Memory usage: {memory_usage['system_memory_percent']:.1f}%")
                
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
                    print(f"   ✅ Downloaded successfully to: {result}")
                else:
                    print(f"   ❌ Failed to download: {key}")
                processed_count += 1
            
            # Download and prepare material files
            redis_manager.update_job_status(task_id, JobStatus.PROCESSING, f"Downloading material files from Wasabi")
            print(f"🎨 [TASK {task_id}] Starting download of material files...")
            total_materials = sum(len(textures) for textures in materials.values())
            material_count = 0
            
            for mat_id, textures in materials.items():
                print(f"   📦 Processing material group: {mat_id} ({len(textures)} textures)")
                for tex_type, path in textures.items():
                    # Check memory during processing
                    if not memory_manager.is_memory_available():
                        memory_usage = memory_manager.get_memory_usage()
                        raise Exception(f"Insufficient memory during material processing: {memory_usage['system_memory_percent']:.1f}%")
                    
                    print(f"   📥 [TASK {task_id}] Downloading material {material_count + 1}/{total_materials}:")
                    print(f"      - Material ID: {mat_id}")
                    print(f"      - Texture type: {tex_type}")
                    print(f"      - Target path: {path}")
                    
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
                        print(f"      ✅ Downloaded successfully to: {result}")
                    else:
                        print(f"      ❌ Failed to download: {tex_type}")
                    processed_count += 1
                    material_count += 1
            
            # Create zip file
            print(f"📦 [TASK {task_id}] Creating validation package...")
            print(f"   - Total local files: {len(all_local_files)}")
            print(f"   - Download directory: {download_dir}")
            
            redis_manager.update_job_status(task_id, JobStatus.PROCESSING, "Creating zip package for validation")
            zip_path = os.path.join(zip_download_dir, f"{job_id}.zip")
            print(f"   - Zip file path: {zip_path}")
            
            FileProcessor.zip_files(zip_path, download_dir)
            
            # Check if zip file was created successfully
            if os.path.exists(zip_path):
                zip_size = os.path.getsize(zip_path)
                print(f"   ✅ Zip file created successfully: {zip_size} bytes")
            else:
                print(f"   ❌ Zip file creation failed: {zip_path}")
                raise Exception("Failed to create zip file")
            
            # Send to validator and update database
            print(f"🔍 [TASK {task_id}] Sending to validator...")
            print(f"   - Zip file: {zip_path}")
            print(f"   - SKU ID: {sku_id}")
            print(f"   - Job ID: {job_id}")
            print(f"   - Username: {username}")
            print(f"   - Campaign: {campaign}")
            print(f"   - Row ID: {row_id}")
            
            redis_manager.update_job_status(task_id, JobStatus.PROCESSING, "Sending files to validation service")
            validation_result = ValidationService.send_to_validator(zip_path, sku_id, job_id, username, campaign, row_id)
            
            print(f"📋 [TASK {task_id}] Validation result: {validation_result}")
            
            # Only upload files if validation passed
            if validation_result:
                redis_manager.update_job_status(task_id, JobStatus.UPLOADING, f"Uploading {len(all_local_files)} files to SFTP server")
                print(f"⬆️ [TASK {task_id}] Starting upload of {len(all_local_files)} files to SFTP...")
                for i, local_path in enumerate(all_local_files):
                    relative_path = os.path.relpath(local_path, download_dir)
                    remote_path = os.path.join(remote_base_dir, relative_path)
                    
                    print(f"   📤 [TASK {task_id}] Uploading file {i + 1}/{len(all_local_files)}:")
                    print(f"      - Local: {local_path}")
                    print(f"      - Remote: {remote_path}")
                    
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
                    
                    try:
                        SFTPManager.upload_to_sftp(sftp, local_path, remote_path)
                        print(f"      ✅ Uploaded successfully")
                    except Exception as e:
                        print(f"      ❌ Upload failed: {e}")
                        raise e
            else:
                print(f"❌ [TASK {task_id}] Validation failed - skipping file upload")
                redis_manager.update_job_status(task_id, JobStatus.COMPLETED, "Validation failed - files not uploaded")
            
            # Cleanup
            redis_manager.update_job_status(task_id, JobStatus.PROCESSING, "Cleaning up temporary files")
            print(f"🧹 [TASK {task_id}] Cleaning up temporary files...")
            FileProcessor.cleanup_files(all_local_files, zip_path, download_dir)
            print(f"   ✅ Cleanup completed")
            
            # Task completed successfully - remove from Redis immediately
            redis_manager.client.delete(f"job:{task_id}")
            print(f"🎉 [TASK {task_id}] Job completed successfully and removed from Redis!")
            
            # Return validation result for reference, but task status is always completed
            if validation_result:
                return {"status": "completed", "message": "Job completed successfully", "validation_result": "passed"}
            else:
                return {"status": "completed", "message": "Job completed successfully - validation failed, files not uploaded", "validation_result": "failed"}
        
        finally:
            # Close SFTP connection
            print(f"🔌 [TASK {task_id}] Closing SFTP connection...")
            sftp.close()
            transport.close()
            print(f"   ✅ SFTP connection closed")
    
    except Retry:
        print(f"🔄 [TASK {task_id}] Task retry requested")
        raise
    except Exception as e:
        error_msg = f"Job processing failed: {str(e)}"
        print(f"💥 [TASK {task_id}] ERROR: {error_msg}")
        print(f"   - Job ID: {job_id}")
        print(f"   - SKU ID: {sku_id}")
        print(f"   - Username: {username}")
        print(f"   - Campaign: {campaign}")
        print(f"   - Row ID: {row_id}")
        print(f"   - Exception type: {type(e).__name__}")
        print(f"   - Exception details: {str(e)}")
        
        # Remove failed job from Redis immediately (no historical data)
        redis_manager.client.delete(f"job:{task_id}")
        print(f"🗑️ [TASK {task_id}] Failed job removed from Redis immediately")
        
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
        
        print(f"🚀 [BATCH {batch_id}] Starting batch processing of {len(job_requests)} jobs")
        
        # Start all jobs asynchronously without waiting for results
        for i, job_req in enumerate(job_requests):
            print(f"📤 [BATCH {batch_id}] Starting job {i + 1}/{len(job_requests)}: {job_req['job_id']}")
            
            # Start individual job task
            task_result = process_job_task.delay(
                job_req['job_id'],
                job_req['username'],
                job_req['campaign'],
                job_req.get('row_id')
            )
            
            # Create Redis job status entry for individual job
            redis_manager.create_job_status(
                job_req['job_id'],
                task_result.id,  # Use Celery task ID as primary task ID
                job_req['username'],
                job_req['campaign'],
                job_req.get('row_id'),
                celery_task_id=task_result.id
            )
            
            results.append({
                "job_id": job_req['job_id'],
                "task_id": task_result.id,
                "status": "started",
                "index": i + 1
            })
        
        print(f"✅ [BATCH {batch_id}] Started {len(results)} jobs successfully")
        
        return {
            "batch_id": batch_id,
            "total_jobs": len(job_requests),
            "started_jobs": len(results),
            "job_results": results,
            "status": "started",
            "message": f"Started {len(results)} jobs in batch"
        }
        
    except Exception as e:
        error_msg = f"Batch processing failed: {str(e)}"
        print(f"❌ [BATCH {batch_id}] Error in batch processing: {e}")
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


# cleanup_failed_job function removed - failed tasks are now removed immediately


# cleanup_old_jobs function removed - no historical data is kept in Redis


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
