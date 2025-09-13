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
import zipfile
import tempfile
import shutil
from botocore.exceptions import ClientError
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


@celery_app.task(bind=True, name='tasks.process_file_upload_task', autoretry_for=(Exception,), retry_kwargs={'max_retries': 2, 'countdown': 60})
def process_file_upload_task(
    self,
    job_id: str,
    row_id: Optional[int] = None,
    delivery_file_path: Optional[str] = None,
    usdz_file_path: Optional[str] = None,
    glb_file_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Process file upload task - handles delivery files, USDZ files, and GLB files
    """
    task_id = self.request.id
    
    try:
        # Update status to processing
        redis_manager.update_job_status(task_id, JobStatus.FILE_UPLOAD_PROCESSING, "Initializing file upload processing")
        
        # Get job details from database
        print(f"🔍 [UPLOAD TASK {task_id}] Getting job details for job_id: {job_id}")
        conn = DatabaseManager.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT sku_id, campaign, job_status FROM job_details WHERE job_id = %s", (job_id,))
            job_details = cursor.fetchone()
            
            if not job_details:
                raise Exception(f"Job not found: {job_id}")
            
            # Extract job details
            sku_id = job_details[0]
            campaign = job_details[1]
            job_status = job_details[2]
            
            print(f"📊 [UPLOAD TASK {task_id}] Job details:")
            print(f"   - Job ID: {job_id}")
            print(f"   - SKU ID: {sku_id}")
            print(f"   - Campaign: {campaign}")
            print(f"   - Job Status: {job_status}")
            
        finally:
            cursor.close()
            conn.close()
        
        # Check if job is already approved
        if job_status in ['IAPPROVED', 'EAPPROVED']:
            print(f"⚠️ [UPLOAD TASK {task_id}] Job already approved: {job_status}")
            redis_manager.update_job_status(task_id, JobStatus.FILE_UPLOAD_COMPLETED, f"Job already approved: {job_status}")
            return {"status": "completed", "message": f"Job already approved: {job_status}", "upload_status": "already"}
        
        # Get current upload count
        conn = DatabaseManager.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT COUNT(*) FROM file_upload_reports WHERE job_id = %s", (job_id,))
            upload_count = cursor.fetchone()[0] + 1
            print(f"📊 [UPLOAD TASK {task_id}] Upload count: {upload_count}")
        finally:
            cursor.close()
            conn.close()
        
        # Initialize file validation flags
        deliverable_validation = "1"
        usdz_validation = "1"
        glb_validation = "1"
        
        # Initialize file paths (like PHP - start as None/null)
        usdz_path = None
        glb_path = None
        
        # Get current datetime
        current_datetime = redis_manager.get_current_ny_time_str()
        
        # Initialize S3 client (assuming FileProcessor has S3 functionality)
        # We'll need to add S3 client initialization here
        import boto3
        s3_client = boto3.client(
            's3',
            aws_access_key_id=settings.wasabi_access_key,
            aws_secret_access_key=settings.wasabi_secret_key,
            endpoint_url=settings.wasabi_endpoint,
            region_name=settings.wasabi_region
        )
        
        # Process delivery file (ZIP) - Enhanced with PHP-like logic
        if delivery_file_path and os.path.exists(delivery_file_path):
            print(f"📦 [UPLOAD TASK {task_id}] Processing delivery file: {delivery_file_path}")
            redis_manager.update_job_status(
                task_id, 
                JobStatus.FILE_UPLOAD_PROCESSING, 
                "Processing delivery ZIP file",
                {
                    "current_step": "delivery_file_processing",
                    "step_description": "Extracting and processing delivery ZIP file",
                    "files_processed": 0,
                    "total_files": 0,
                    "percentage": 0
                }
            )
            
            try:
                # Extract ZIP file to temporary directory
                extract_path = tempfile.mkdtemp(prefix=f"delivery_{job_id}_")
                print(f"   - Extract path: {extract_path}")
                
                with zipfile.ZipFile(delivery_file_path, 'r') as zip_ref:
                    zip_ref.extractall(extract_path)
                    file_list = zip_ref.namelist()
                    print(f"   📦 ZIP contains {len(file_list)} files")
                
                # Update progress with total file count
                redis_manager.update_job_status(
                    task_id, 
                    JobStatus.FILE_UPLOAD_PROCESSING, 
                    f"Extracted {len(file_list)} files from ZIP, starting upload",
                    {
                        "current_step": "delivery_file_upload",
                        "step_description": "Uploading extracted files to S3",
                        "files_processed": 0,
                        "total_files": len(file_list),
                        "percentage": 0
                    }
                )
                
                # Process extracted files recursively (like PHP RecursiveIteratorIterator)
                upload_success = True
                processed_files = 0
                
                for root, dirs, files in os.walk(extract_path):
                    for file in files:
                        local_file_path = os.path.join(root, file)
                        relative_path = os.path.relpath(local_file_path, extract_path)
                        
                        # Normalize path separators for S3 (like PHP)
                        relative_path = relative_path.replace('\\', '/')
                        
                        print(f"   📄 Processing file {processed_files + 1}: {relative_path}")
                        
                        # Determine S3 key based on file extension (matching PHP logic)
                        extension = os.path.splitext(file)[1].lower()
                        s3_key = ""
                        
                        if extension == '.glb':
                            if glb_path is None:
                                # First GLB file becomes the main GLB file
                                glb_path = f"jobs/{job_id}/GLB_files/mesh.glb"
                                s3_key = glb_path
                                print(f"      🎮 Set as main GLB file: {s3_key}")
                            else:
                                # Additional GLB files go to Delivery_files
                                s3_key = f"jobs/{job_id}/Delivery_files/{relative_path}"
                                print(f"      🎮 Additional GLB file: {s3_key}")
                        elif extension == '.usdz':
                            if usdz_path is None:
                                # First USDZ file becomes the main USDZ file
                                usdz_path = f"jobs/{job_id}/usdz_files/mesh.usdz"
                                s3_key = usdz_path
                                print(f"      📱 Set as main USDZ file: {s3_key}")
                            else:
                                # Additional USDZ files go to Delivery_files
                                s3_key = f"jobs/{job_id}/Delivery_files/{relative_path}"
                                print(f"      📱 Additional USDZ file: {s3_key}")
                        else:
                            # All other files go to Delivery_files
                            s3_key = f"jobs/{job_id}/Delivery_files/{relative_path}"
                            print(f"      📦 Delivery file: {s3_key}")
                        
                        # Validate S3 key
                        if not s3_key:
                            print(f"      ❌ Empty S3 key for file: {local_file_path}")
                            upload_success = False
                            continue
                        
                        # Upload to S3 with error handling (like PHP)
                        try:
                            s3_client.upload_file(
                                local_file_path,
                                settings.bucket_name,
                                s3_key,
                                ExtraArgs={'ACL': 'private'}
                            )
                            print(f"      ✅ Uploaded successfully: {s3_key}")
                            
                            # Update job_files table (like PHP database operations)
                            DatabaseManager.update_job_files_table(job_id, s3_key, current_datetime)
                            
                        except ClientError as e:
                            print(f"      ❌ S3 upload failed for {s3_key}: {e}")
                            upload_success = False
                        
                        processed_files += 1
                        
                        # Update progress after each file upload
                        percentage = int((processed_files / len(file_list)) * 100) if file_list else 0
                        redis_manager.update_job_status(
                            task_id, 
                            JobStatus.FILE_UPLOAD_PROCESSING, 
                            f"Uploaded {processed_files}/{len(file_list)} files from delivery ZIP",
                            {
                                "current_step": "delivery_file_upload",
                                "step_description": "Uploading extracted files to S3",
                                "files_processed": processed_files,
                                "total_files": len(file_list),
                                "percentage": percentage,
                                "current_file": os.path.basename(relative_path)
                            }
                        )
                
                deliverable_validation = "1" if upload_success else "0"
                print(f"   📊 Delivery processing complete: {processed_files} files, success: {upload_success}")
                
                # Clean up extracted files (like PHP shell_exec cleanup)
                try:
                    shutil.rmtree(extract_path)
                    print(f"   🧹 Cleaned up extraction directory: {extract_path}")
                except Exception as e:
                    print(f"   ⚠️ Failed to clean up extraction directory: {e}")
                
            except zipfile.BadZipFile as e:
                print(f"❌ [UPLOAD TASK {task_id}] Invalid ZIP file: {e}")
                deliverable_validation = "0"
            except Exception as e:
                print(f"❌ [UPLOAD TASK {task_id}] Delivery file processing failed: {e}")
                deliverable_validation = "0"
        else:
            # No delivery file provided - set validation to 1 (like PHP logic)
            deliverable_validation = "1"
            print(f"📦 [UPLOAD TASK {task_id}] No delivery file provided - validation set to 1")
        
        # Process USDZ file - Following exact PHP pattern
        if usdz_file_path and os.path.exists(usdz_file_path):
            print(f"📱 [UPLOAD TASK {task_id}] Processing USDZ file: {usdz_file_path}")
            
            source_path_usdz = usdz_file_path
            file_name_usdz = "mesh.usdz"
            s3_key_usdz = f"jobs/{job_id}/usdz_files/{file_name_usdz}"
            
            try:
                s3_client.upload_file(
                    source_path_usdz,
                    settings.bucket_name,
                    s3_key_usdz,
                    ExtraArgs={'ACL': 'private'}
                )
                
                usdz_path = s3_key_usdz
                usdz_validation = "1"
                print(f"   ✅ USDZ uploaded: {s3_key_usdz}")
                
                # Update job_files table (like PHP database operations)
                DatabaseManager.update_job_files_table(job_id, usdz_path, current_datetime)
                
            except ClientError as e:
                print(f"   ❌ USDZ S3 upload failed: {e}")
                usdz_validation = "0"
            except Exception as e:
                print(f"   ❌ USDZ processing failed: {e}")
                usdz_validation = "0"
        else:
            # No USDZ file provided - set validation to 1 (like PHP logic)
            usdz_validation = "1"
            if usdz_path is None:
                usdz_path = ""
            print(f"📱 [UPLOAD TASK {task_id}] No USDZ file provided - validation set to 1")
        
        # Process GLB file - Following exact PHP pattern
        if glb_file_path and os.path.exists(glb_file_path):
            print(f"🎮 [UPLOAD TASK {task_id}] Processing GLB file: {glb_file_path}")
            
            source_path_glb = glb_file_path
            file_name_glb = "mesh.glb"
            s3_key_glb = f"jobs/{job_id}/GLB_files/{file_name_glb}"
            
            try:
                s3_client.upload_file(
                    source_path_glb,
                    settings.bucket_name,
                    s3_key_glb,
                    ExtraArgs={'ACL': 'private'}
                )
                
                glb_path = s3_key_glb
                glb_validation = "1"
                print(f"   ✅ GLB uploaded: {s3_key_glb}")
                
                # Update job_files table (like PHP database operations)
                DatabaseManager.update_job_files_table(job_id, glb_path, current_datetime)
                
            except ClientError as e:
                print(f"   ❌ GLB S3 upload failed: {e}")
                glb_validation = "0"
            except Exception as e:
                print(f"   ❌ GLB processing failed: {e}")
                glb_validation = "0"
        else:
            # No GLB file provided - set validation to 1 (like PHP logic)
            glb_validation = "1"
            if glb_path is None:
                glb_path = ""
            print(f"🎮 [UPLOAD TASK {task_id}] No GLB file provided - validation set to 1")
        
        # Final validation check (matching PHP logic)
        print(f"📊 [UPLOAD TASK {task_id}] Upload validation summary:")
        print(f"   - Deliverable validation: {deliverable_validation}")
        print(f"   - USDZ validation: {usdz_validation}")
        print(f"   - GLB validation: {glb_validation}")
        print(f"   - USDZ path: {usdz_path if usdz_path else 'None'}")
        print(f"   - GLB path: {glb_path if glb_path else 'None'}")
        
        if deliverable_validation == '1' and usdz_validation == "1" and glb_validation == "1":
            print(f"✅ [UPLOAD TASK {task_id}] All files uploaded successfully")
            redis_manager.update_job_status(
                task_id, 
                JobStatus.FILE_UPLOAD_PROCESSING, 
                "All files uploaded successfully, updating database",
                {
                    "current_step": "database_update",
                    "step_description": "Updating database with upload results",
                    "files_processed": 0,
                    "total_files": 0,
                    "percentage": 0,
                    "validation_results": {
                        "deliverable": deliverable_validation,
                        "usdz": usdz_validation,
                        "glb": glb_validation
                    }
                }
            )
            
            # Update database with successful upload (matching PHP logic)
            try:
                # Insert into file_upload_reports table (like PHP)
                conn = DatabaseManager.get_connection()
                cursor = conn.cursor()
                
                try:
                    # Update progress for database operations
                    redis_manager.update_job_status(
                        task_id, 
                        JobStatus.FILE_UPLOAD_PROCESSING, 
                        "Inserting file upload report",
                        {
                            "current_step": "database_update",
                            "step_description": "Inserting file upload report",
                            "files_processed": 1,
                            "total_files": 2,
                            "percentage": 50
                        }
                    )
                    
                    # Insert file upload report
                    insert_sql = """
                        INSERT INTO file_upload_reports 
                        (job_id, sku_id, upload_count, campagin, file_status, QC_status, delivery_path, glb_path, timestamp, last_update) 
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """
                    cursor.execute(insert_sql, (
                        job_id, sku_id, upload_count, campaign, 'IAPPROVED', 'INTERNAL', 
                        usdz_path, glb_path, current_datetime, current_datetime
                    ))
                    
                    # Update progress for job details update
                    redis_manager.update_job_status(
                        task_id, 
                        JobStatus.FILE_UPLOAD_PROCESSING, 
                        "Updating job details",
                        {
                            "current_step": "database_update",
                            "step_description": "Updating job details",
                            "files_processed": 2,
                            "total_files": 2,
                            "percentage": 100
                        }
                    )
                    
                    # Update job_details table (like PHP)
                    update_sql = """
                        UPDATE job_details 
                        SET job_status = 'WIP', is_uploaded = 1, updateTime = %s 
                        WHERE id = %s
                    """
                    cursor.execute(update_sql, (current_datetime, row_id))
                    
                    conn.commit()
                    print(f"   ✅ Database updated successfully")
                    
                    redis_manager.update_job_status(task_id, JobStatus.FILE_UPLOAD_COMPLETED, "File upload completed successfully")
                    
                    # Remove from Redis
                    redis_manager.client.delete(f"job:{task_id}")
                    
                    return {
                        "status": "completed", 
                        "message": "File upload completed successfully", 
                        "upload_status": "ok",
                        "upload_count": upload_count,
                        "usdz_path": usdz_path,
                        "glb_path": glb_path
                    }
                    
                except Exception as e:
                    conn.rollback()
                    print(f"   ❌ Database update failed: {e}")
                    redis_manager.update_job_status(task_id, JobStatus.FILE_UPLOAD_FAILED, "Database update failed")
                    
                    # Remove from Redis
                    redis_manager.client.delete(f"job:{task_id}")
                    
                    return {
                        "status": "failed", 
                        "message": "File upload succeeded but database update failed",
                        "upload_status": "failed"
                    }
                    
                finally:
                    cursor.close()
                    conn.close()
                    
            except Exception as e:
                print(f"   ❌ Database connection error: {e}")
                redis_manager.update_job_status(task_id, JobStatus.FILE_UPLOAD_FAILED, f"Database connection error: {str(e)}")
                
                # Remove from Redis
                redis_manager.client.delete(f"job:{task_id}")
                
                return {
                    "status": "failed", 
                    "message": f"Database connection error: {str(e)}",
                    "upload_status": "failed"
                }
        else:
            print(f"❌ [UPLOAD TASK {task_id}] File upload validation failed")
            print(f"   - Deliverable: {deliverable_validation}")
            print(f"   - USDZ: {usdz_validation}")
            print(f"   - GLB: {glb_validation}")
            
            redis_manager.update_job_status(task_id, JobStatus.FILE_UPLOAD_FAILED, "File upload validation failed")
            
            # Remove from Redis
            redis_manager.client.delete(f"job:{task_id}")
            
            return {
                "status": "failed", 
                "message": "File upload failed - validation check failed",
                "upload_status": "failed",
                "validation_details": {
                    "deliverable": deliverable_validation,
                    "usdz": usdz_validation,
                    "glb": glb_validation
                }
            }
    
    except Exception as e:
        error_msg = f"File upload processing failed: {str(e)}"
        print(f"💥 [UPLOAD TASK {task_id}] ERROR: {error_msg}")
        
        # Remove failed job from Redis
        redis_manager.client.delete(f"job:{task_id}")
        
        return {"status": "failed", "message": error_msg}
