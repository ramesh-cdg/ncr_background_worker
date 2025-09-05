"""
Redis job management module
"""
import redis
import json
from typing import Dict, Any, Optional
from datetime import datetime
import pytz
from config import settings
from models import JobStatus


class RedisManager:
    """Redis job management operations"""
    
    def __init__(self):
        self.client = redis.Redis(
            host=settings.redis_host, 
            port=settings.redis_port, 
            db=settings.redis_db, 
            decode_responses=True
        )
        self.timezone = pytz.timezone(settings.timezone)
    
    def get_current_ny_time(self) -> datetime:
        """Get current time in America/New_York timezone"""
        return datetime.now(self.timezone)
    
    def get_current_ny_time_str(self) -> str:
        """Get current time in America/New_York timezone as formatted string"""
        return self.get_current_ny_time().strftime('%Y-%m-%d %H:%M:%S')
    
    def create_job_status(
        self, 
        job_id: str, 
        task_id: str, 
        username: str, 
        campaign: str, 
        row_id: Optional[int] = None,
        celery_task_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create initial job status in Redis - replaces any existing tasks for this job_id"""
        
        # Clean up any existing tasks for this job_id (keep only latest)
        self.cleanup_old_tasks_for_job_id(job_id)
        
        job_data = {
            "job_id": job_id,
            "task_id": task_id,
            "celery_task_id": celery_task_id or "",
            "username": username,
            "campaign": campaign,
            "row_id": str(row_id) if row_id else "",
            "status": JobStatus.PENDING,
            "progress": json.dumps({
                "current_step": "Initializing",
                "total_files": 0,
                "processed_files": 0,
                "current_file": "",
                "percentage": 0
            }),
            "message": "Job created and queued",
            "timestamp": self.get_current_ny_time().isoformat(),
            "logs": json.dumps([])
        }
        
        self.client.hset(f"job:{task_id}", mapping=job_data)
        self.client.expire(f"job:{task_id}", settings.job_expire_hours * 3600)  # Expire in hours
        
        return job_data
    
    def cleanup_old_tasks_for_job_id(self, job_id: str) -> None:
        """Clean up old tasks for a specific job_id, keeping only the latest one"""
        try:
            print(f"🧹 [REDIS] Cleaning up old tasks for job_id: {job_id}")
            
            # Find all tasks for this job_id
            tasks_to_cleanup = []
            for key in self.client.scan_iter("job:*"):
                task_id = key.split(":")[1]
                job_data = self.get_job_status(task_id)
                if job_data and job_data.get("job_id") == job_id:
                    tasks_to_cleanup.append((task_id, job_data.get("timestamp", "")))
            
            if len(tasks_to_cleanup) > 0:
                print(f"   Found {len(tasks_to_cleanup)} existing tasks for job_id {job_id}")
                
                # Sort by timestamp and keep only the latest
                tasks_to_cleanup.sort(key=lambda x: x[1], reverse=True)
                latest_task_id = tasks_to_cleanup[0][0]
                
                # Delete all except the latest
                for task_id, timestamp in tasks_to_cleanup[1:]:
                    self.client.delete(f"job:{task_id}")
                    print(f"   ✅ Cleaned up old task: {task_id}")
                
                print(f"   ✅ Kept latest task: {latest_task_id}")
            else:
                print(f"   No existing tasks found for job_id {job_id}")
                
        except Exception as e:
            print(f"❌ [REDIS] Error cleaning up old tasks for job_id {job_id}: {e}")
    
    def update_job_status(
        self, 
        task_id: str, 
        status: str = None, 
        message: str = None, 
        progress: Dict = None, 
        log: str = None
    ):
        """Update job status in Redis"""
        try:
            current_data = self.client.hgetall(f"job:{task_id}")
            if current_data:
                updates = {}
                
                if status:
                    updates["status"] = status
                if message:
                    updates["message"] = message
                if progress:
                    updates["progress"] = json.dumps(progress)
                if log:
                    current_logs = json.loads(current_data.get("logs", "[]"))
                    current_logs.append({
                        "timestamp": self.get_current_ny_time_str(),
                        "message": log
                    })
                    updates["logs"] = json.dumps(current_logs)
                
                updates["timestamp"] = self.get_current_ny_time().isoformat()
                
                if updates:
                    self.client.hset(f"job:{task_id}", mapping=updates)
                    
        except Exception as e:
            print(f"Error updating job status: {e}")
    
    def get_job_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get job status from Redis"""
        try:
            job_data = self.client.hgetall(f"job:{task_id}")
            if job_data:
                # Convert JSON strings back to proper types
                if "progress" in job_data and job_data["progress"]:
                    job_data["progress"] = json.loads(job_data["progress"])
                if "logs" in job_data and job_data["logs"]:
                    job_data["logs"] = json.loads(job_data["logs"])
                return job_data
            return None
        except Exception as e:
            print(f"Error getting job status: {e}")
            return None
    
    def get_active_jobs(self, username: Optional[str] = None, campaign: Optional[str] = None) -> list:
        """Get active jobs from Redis with optional filtering by username and/or campaign"""
        active_jobs = []
        try:
            print(f"🔍 [REDIS] Getting active jobs with filters:")
            print(f"   - Username filter: {username}")
            print(f"   - Campaign filter: {campaign}")
            
            for key in self.client.scan_iter("job:*"):
                task_id = key.split(":")[1]
                job_data = self.get_job_status(task_id)
                if job_data and job_data["status"] not in [JobStatus.COMPLETED, JobStatus.FAILED]:
                    # Apply filters
                    job_username = job_data.get("username", "")
                    job_campaign = job_data.get("campaign", "")
                    
                    # Check username filter
                    if username and username.lower() not in job_username.lower():
                        continue
                    
                    # Check campaign filter
                    if campaign and campaign.lower() not in job_campaign.lower():
                        continue
                    
                    active_jobs.append({
                        "task_id": task_id,
                        "celery_task_id": job_data.get("celery_task_id", ""),
                        "job_id": job_data["job_id"],
                        "username": job_username,
                        "campaign": job_campaign,
                        "row_id": job_data.get("row_id", ""),
                        "status": job_data["status"],
                        "message": job_data["message"],
                        "timestamp": job_data["timestamp"]
                    })
            
            print(f"   ✅ Found {len(active_jobs)} active jobs matching filters")
            
        except Exception as e:
            print(f"❌ [REDIS] Error getting active jobs: {e}")
        
        return active_jobs
    
    def get_jobs(self, username: Optional[str] = None, campaign: Optional[str] = None, 
                 status: Optional[str] = None, limit: int = 100) -> list:
        """Get jobs from Redis with filtering options"""
        jobs = []
        try:
            print(f"🔍 [REDIS] Getting jobs with filters:")
            print(f"   - Username filter: {username}")
            print(f"   - Campaign filter: {campaign}")
            print(f"   - Status filter: {status}")
            print(f"   - Limit: {limit}")
            
            for key in self.client.scan_iter("job:*"):
                if len(jobs) >= limit:
                    break
                    
                task_id = key.split(":")[1]
                job_data = self.get_job_status(task_id)
                if job_data:
                    # Apply filters
                    job_username = job_data.get("username", "")
                    job_campaign = job_data.get("campaign", "")
                    job_status = job_data.get("status", "")
                    
                    # Check username filter
                    if username and username.lower() not in job_username.lower():
                        continue
                    
                    # Check campaign filter
                    if campaign and campaign.lower() not in job_campaign.lower():
                        continue
                    
                    # Check status filter
                    if status and status.lower() != job_status.lower():
                        continue
                    
                    jobs.append({
                        "task_id": task_id,
                        "celery_task_id": job_data.get("celery_task_id", ""),
                        "job_id": job_data["job_id"],
                        "username": job_username,
                        "campaign": job_campaign,
                        "row_id": job_data.get("row_id", ""),
                        "status": job_status,
                        "message": job_data.get("message", ""),
                        "timestamp": job_data.get("timestamp", ""),
                        "progress": job_data.get("progress", {}),
                        "logs": job_data.get("logs", [])
                    })
            
            print(f"   ✅ Found {len(jobs)} jobs matching filters")
            
        except Exception as e:
            print(f"❌ [REDIS] Error getting jobs: {e}")
        
        return jobs
    
    def get_jobs_by_job_id(self, job_id: str) -> list:
        """Get all jobs (tasks) for a specific job_id"""
        jobs = []
        try:
            print(f"🔍 [REDIS] Getting jobs by job_id: {job_id}")
            
            for key in self.client.scan_iter("job:*"):
                task_id = key.split(":")[1]
                job_data = self.get_job_status(task_id)
                if job_data and job_data.get("job_id") == job_id:
                    jobs.append({
                        "task_id": task_id,
                        "celery_task_id": job_data.get("celery_task_id", ""),
                        "job_id": job_data["job_id"],
                        "username": job_data.get("username", ""),
                        "campaign": job_data.get("campaign", ""),
                        "row_id": job_data.get("row_id", ""),
                        "status": job_data.get("status", ""),
                        "message": job_data.get("message", ""),
                        "timestamp": job_data.get("timestamp", ""),
                        "progress": job_data.get("progress", {}),
                        "logs": job_data.get("logs", [])
                    })
            
            print(f"   ✅ Found {len(jobs)} jobs for job_id: {job_id}")
            
        except Exception as e:
            print(f"❌ [REDIS] Error getting jobs by job_id {job_id}: {e}")
        
        return jobs
    
    # get_batches_by_username function removed - no batch data stored in Redis
    
    def get_job_by_celery_task_id(self, celery_task_id: str) -> Optional[Dict[str, Any]]:
        """Get job data by Celery task ID"""
        try:
            for key in self.client.scan_iter("job:*"):
                task_id = key.split(":")[1]
                job_data = self.get_job_status(task_id)
                if job_data and job_data.get("celery_task_id") == celery_task_id:
                    return job_data
            return None
        except Exception as e:
            print(f"Error getting job by Celery task ID: {e}")
            return None
    
    def test_connection(self) -> bool:
        """Test Redis connection"""
        try:
            self.client.ping()
            return True
        except:
            return False


# Global Redis manager instance
redis_manager = RedisManager()
