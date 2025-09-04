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
        """Create initial job status in Redis"""
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
    
    def get_active_jobs(self) -> list:
        """Get all active jobs from Redis"""
        active_jobs = []
        try:
            for key in self.client.scan_iter("job:*"):
                task_id = key.split(":")[1]
                job_data = self.get_job_status(task_id)
                if job_data and job_data["status"] not in [JobStatus.COMPLETED, JobStatus.FAILED]:
                    active_jobs.append({
                        "task_id": task_id,
                        "celery_task_id": job_data.get("celery_task_id", ""),
                        "job_id": job_data["job_id"],
                        "username": job_data.get("username", ""),
                        "campaign": job_data.get("campaign", ""),
                        "row_id": job_data.get("row_id", ""),
                        "status": job_data["status"],
                        "message": job_data["message"],
                        "timestamp": job_data["timestamp"]
                    })
        except Exception as e:
            print(f"Error getting active jobs: {e}")
        
        return active_jobs
    
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
