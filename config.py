"""
Configuration module for NCR Upload API
"""
import os
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Wasabi S3 Configuration
    wasabi_access_key: str = "JJRP6J4ARVDUM3HBFI0T"
    wasabi_secret_key: str = "7wjNIWE2p52MzHqLhGL51t7yUOArhJAAEK7LwJVK"
    wasabi_region: str = "us-central-1"
    wasabi_endpoint: str = "https://s3.us-central-1.wasabisys.com"
    bucket_name: str = "ncrfiles"
    
    # Database Configuration
    db_host: str = "localhost"
    db_user: str = "d-admin"
    db_pass: str = "C!0ud$24"
    db_name: str = "ncr3d_crm"
    
    # Redis Configuration
    redis_host: str = "redis"
    redis_port: int = 6379  # Internal Redis port
    redis_db: int = 0
    
    # SFTP Configuration
    sftp_host: str = "modeling.arcstudio.ai"
    sftp_port: int = 22
    sftp_username: str = "modeling"
    sftp_password: str = "eruCnoWz3GzvC5rE6K42Sv99"
    
    # API Configuration
    api_title: str = "NCR Upload API"
    api_version: str = "1.0.0"
    api_host: str = "0.0.0.0"
    api_port: int = 8001
    
    # Gunicorn Configuration
    gunicorn_workers: int = 8
    gunicorn_worker_class: str = "uvicorn.workers.UvicornWorker"
    gunicorn_timeout: int = 120
    gunicorn_keepalive: int = 2
    gunicorn_max_requests: int = 1000
    gunicorn_max_requests_jitter: int = 100
    
    # Validator API Configuration
    validator_api_url: str = "https://bond-api.nextechar.com/api/validator/validate"
    validator_api_key: str = "13D8429DBDF8C3DD437FB35182A98_BOND"
    
    # Timezone Configuration
    timezone: str = "America/New_York"
    
    # Job Configuration
    job_expire_hours: int = 24
    
    # Celery Configuration
    @property
    def celery_broker_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/0"
    
    @property
    def celery_result_backend(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/0"
    celery_task_serializer: str = "json"
    celery_result_serializer: str = "json"
    celery_accept_content: list = ["json"]
    celery_timezone: str = "America/New_York"
    celery_enable_utc: bool = True
    
    # Worker Configuration
    celery_worker_concurrency: int = 8
    celery_worker_prefetch_multiplier: int = 1  # Only prefetch 1 task per worker
    celery_worker_max_tasks_per_child: int = 1000
    celery_worker_max_memory_per_child: int = 2000000  # 2GB in KB
    
    # Task Configuration
    celery_task_soft_time_limit: int = 3600  # 1 hour
    celery_task_time_limit: int = 3900  # 1 hour 5 minutes
    celery_task_acks_late: bool = True
    celery_worker_disable_rate_limits: bool = True
    
    # Memory Management
    max_memory_usage_percent: int = 85  # Max 85% of available memory for 54GB system
    memory_check_interval: int = 30  # Check memory every 30 seconds
    
    # Batch Processing
    batch_size: int = 10  # Process up to 10 jobs in parallel for 54GB system
    batch_timeout: int = 300  # 5 minutes timeout for batch processing
    
    class Config:
        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings = Settings()
