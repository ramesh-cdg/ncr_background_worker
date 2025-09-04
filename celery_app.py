"""
Celery application configuration and setup
"""
from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown
from config import settings
import psutil
import os


def create_celery_app() -> Celery:
    """Create and configure Celery application"""
    app = Celery('ncr_upload_worker')
    
    # Configure Celery
    app.conf.update(
        # Broker and Result Backend
        broker_url=settings.celery_broker_url,
        result_backend=settings.celery_result_backend,
        
        # Serialization
        task_serializer=settings.celery_task_serializer,
        result_serializer=settings.celery_result_serializer,
        accept_content=settings.celery_accept_content,
        
        # Timezone
        timezone=settings.celery_timezone,
        enable_utc=settings.celery_enable_utc,
        
        # Worker Configuration
        worker_concurrency=settings.celery_worker_concurrency,
        worker_prefetch_multiplier=settings.celery_worker_prefetch_multiplier,
        worker_max_tasks_per_child=settings.celery_worker_max_tasks_per_child,
        worker_max_memory_per_child=settings.celery_worker_max_memory_per_child,
        
        # Concurrency Control - Let Celery handle queueing
        worker_direct=True,  # Direct task execution without prefetching
        task_acks_late=True,  # Acknowledge tasks only after completion
        task_reject_on_worker_lost=True,  # Reject tasks if worker dies
        
        # Task Configuration
        task_soft_time_limit=settings.celery_task_soft_time_limit,
        task_time_limit=settings.celery_task_time_limit,
        worker_disable_rate_limits=settings.celery_worker_disable_rate_limits,
        
        # Task Routes
        task_routes={
            'tasks.process_job_task': {'queue': 'job_processing'},
            'tasks.batch_process_jobs': {'queue': 'batch_processing'},
            'tasks.memory_monitor_task': {'queue': 'monitoring'},
        },
        
        # Task Defaults
        task_default_queue='default',
        task_default_exchange='default',
        task_default_exchange_type='direct',
        task_default_routing_key='default',
        
        # Result Backend Settings
        result_expires=3600,  # 1 hour
        result_persistent=True,
        
        # Worker Settings
        worker_hijack_root_logger=False,
        worker_log_color=False,
        
        # Event Settings - Disable events to fix dispatcher issue
        worker_send_task_events=False,
        task_send_sent_event=False,
        worker_enable_remote_control=False,
        
        # Beat Schedule (for periodic tasks)
        beat_schedule={
            'memory-monitor': {
                'task': 'tasks.memory_monitor_task',
                'schedule': settings.memory_check_interval,
            },
        },
    )
    
    return app


# Create Celery app instance
celery_app = create_celery_app()


@worker_process_init.connect
def worker_process_init_handler(sender=None, **kwargs):
    """Initialize worker process"""
    print(f"Worker process {os.getpid()} initialized")
    # Set process priority to normal
    try:
        process = psutil.Process()
        process.nice(0)  # Set to normal priority
    except Exception as e:
        print(f"Could not set process priority: {e}")


@worker_process_shutdown.connect
def worker_process_shutdown_handler(sender=None, **kwargs):
    """Cleanup on worker shutdown"""
    print(f"Worker process {os.getpid()} shutting down")


class MemoryManager:
    """Memory management utilities for Celery workers"""
    
    @staticmethod
    def get_memory_usage() -> dict:
        """Get current memory usage statistics"""
        process = psutil.Process()
        memory_info = process.memory_info()
        system_memory = psutil.virtual_memory()
        
        return {
            'process_memory_mb': memory_info.rss / 1024 / 1024,
            'process_memory_percent': process.memory_percent(),
            'system_memory_percent': system_memory.percent,
            'system_memory_available_mb': system_memory.available / 1024 / 1024,
            'system_memory_total_mb': system_memory.total / 1024 / 1024,
        }
    
    @staticmethod
    def is_memory_available() -> bool:
        """Check if system has enough memory available"""
        system_memory = psutil.virtual_memory()
        return system_memory.percent < settings.max_memory_usage_percent
    
    @staticmethod
    def get_recommended_concurrency() -> int:
        """Get recommended concurrency based on available memory"""
        memory_stats = MemoryManager.get_memory_usage()
        available_memory_mb = memory_stats['system_memory_available_mb']
        
        # Estimate 200MB per job
        estimated_memory_per_job = 200
        max_concurrent_jobs = int(available_memory_mb / estimated_memory_per_job)
        
        # Ensure minimum of 1 and maximum of configured concurrency
        return max(1, min(max_concurrent_jobs, settings.celery_worker_concurrency))
    
    @staticmethod
    def should_accept_new_job() -> bool:
        """Determine if worker should accept new jobs based on memory"""
        if not MemoryManager.is_memory_available():
            return False
        
        memory_stats = MemoryManager.get_memory_usage()
        process_memory_mb = memory_stats['process_memory_mb']
        
        # Don't accept new jobs if process memory exceeds 500MB
        return process_memory_mb < 500


# Global memory manager instance
memory_manager = MemoryManager()
