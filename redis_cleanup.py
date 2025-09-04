#!/usr/bin/env python3
"""
Redis cleanup and debugging script
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from redis_manager import redis_manager
from models import JobStatus
from datetime import datetime, timedelta

def show_redis_status():
    """Show current Redis status and job counts"""
    print("🔍 REDIS STATUS REPORT")
    print("=" * 60)
    
    try:
        # Get Redis info
        redis_info = redis_manager.client.info()
        print(f"Redis Memory Usage: {redis_info.get('used_memory_human', 'Unknown')}")
        print(f"Connected Clients: {redis_info.get('connected_clients', 'Unknown')}")
        print(f"Total Commands: {redis_info.get('total_commands_processed', 'Unknown')}")
        print()
        
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
        
        jobs_by_status = {
            "pending": [],
            "processing": [],
            "completed": [],
            "failed": [],
            "validation_passed": [],
            "validation_failed": [],
            "uploading": []
        }
        
        print("📊 JOB COUNTS BY STATUS:")
        for key in redis_manager.client.scan_iter("job:*"):
            task_id = key.split(":")[1]
            job_data = redis_manager.get_job_status(task_id)
            if job_data:
                job_counts["total"] += 1
                status = job_data.get("status", "unknown")
                if status in job_counts:
                    job_counts[status] += 1
                    jobs_by_status[status].append({
                        "task_id": task_id,
                        "job_id": job_data.get("job_id", "unknown"),
                        "timestamp": job_data.get("timestamp", "unknown"),
                        "message": job_data.get("message", "")
                    })
        
        for status, count in job_counts.items():
            if status != "total":
                print(f"  {status.upper()}: {count}")
        print(f"  TOTAL: {job_counts['total']}")
        print()
        
        # Show failed jobs details
        if jobs_by_status["failed"]:
            print("❌ FAILED JOBS:")
            for job in jobs_by_status["failed"][:10]:  # Show first 10
                print(f"  - Task ID: {job['task_id']}")
                print(f"    Job ID: {job['job_id']}")
                print(f"    Time: {job['timestamp']}")
                print(f"    Message: {job['message']}")
                print()
            if len(jobs_by_status["failed"]) > 10:
                print(f"  ... and {len(jobs_by_status['failed']) - 10} more failed jobs")
        
        # Show pending jobs details
        if jobs_by_status["pending"]:
            print("⏳ PENDING JOBS:")
            for job in jobs_by_status["pending"][:10]:  # Show first 10
                print(f"  - Task ID: {job['task_id']}")
                print(f"    Job ID: {job['job_id']}")
                print(f"    Time: {job['timestamp']}")
                print(f"    Message: {job['message']}")
                print()
            if len(jobs_by_status["pending"]) > 10:
                print(f"  ... and {len(jobs_by_status['pending']) - 10} more pending jobs")
        
        return job_counts, jobs_by_status
        
    except Exception as e:
        print(f"❌ Error getting Redis status: {e}")
        return None, None

def cleanup_failed_jobs(confirm=False):
    """Clean up failed jobs"""
    if not confirm:
        print("⚠️  This will delete all failed jobs from Redis!")
        response = input("Are you sure? (yes/no): ")
        if response.lower() != 'yes':
            print("❌ Cleanup cancelled")
            return
    
    try:
        cleaned_count = 0
        for key in redis_manager.client.scan_iter("job:*"):
            task_id = key.split(":")[1]
            job_data = redis_manager.get_job_status(task_id)
            if job_data and job_data.get("status") == JobStatus.FAILED:
                redis_manager.client.delete(key)
                cleaned_count += 1
                print(f"✅ Cleaned up failed job: {task_id}")
        
        print(f"\n🎉 Cleaned up {cleaned_count} failed jobs")
        
    except Exception as e:
        print(f"❌ Error cleaning up failed jobs: {e}")

def cleanup_old_jobs(confirm=False, hours=24):
    """Clean up old jobs (completed/failed older than specified hours)"""
    if not confirm:
        print(f"⚠️  This will delete all jobs older than {hours} hours!")
        response = input("Are you sure? (yes/no): ")
        if response.lower() != 'yes':
            print("❌ Cleanup cancelled")
            return
    
    try:
        cleaned_count = 0
        current_time = redis_manager.get_current_ny_time()
        cutoff_time = current_time - timedelta(hours=hours)
        
        for key in redis_manager.client.scan_iter("job:*"):
            task_id = key.split(":")[1]
            job_data = redis_manager.get_job_status(task_id)
            if job_data:
                try:
                    job_timestamp = datetime.fromisoformat(job_data["timestamp"])
                    if job_timestamp < cutoff_time:
                        status = job_data.get("status", "")
                        if status in [JobStatus.COMPLETED, JobStatus.FAILED]:
                            redis_manager.client.delete(key)
                            cleaned_count += 1
                            print(f"✅ Cleaned up old {status} job: {task_id}")
                except Exception as e:
                    print(f"⚠️  Error processing job {task_id}: {e}")
        
        print(f"\n🎉 Cleaned up {cleaned_count} old jobs")
        
    except Exception as e:
        print(f"❌ Error cleaning up old jobs: {e}")

def cleanup_stale_pending_jobs(confirm=False, hours=24):
    """Clean up stale pending jobs (pending for more than specified hours)"""
    if not confirm:
        print(f"⚠️  This will delete all pending jobs older than {hours} hours!")
        response = input("Are you sure? (yes/no): ")
        if response.lower() != 'yes':
            print("❌ Cleanup cancelled")
            return
    
    try:
        cleaned_count = 0
        current_time = redis_manager.get_current_ny_time()
        cutoff_time = current_time - timedelta(hours=hours)
        
        for key in redis_manager.client.scan_iter("job:*"):
            task_id = key.split(":")[1]
            job_data = redis_manager.get_job_status(task_id)
            if job_data and job_data.get("status") == JobStatus.PENDING:
                try:
                    job_timestamp = datetime.fromisoformat(job_data["timestamp"])
                    if job_timestamp < cutoff_time:
                        redis_manager.client.delete(key)
                        cleaned_count += 1
                        print(f"✅ Cleaned up stale pending job: {task_id}")
                except Exception as e:
                    print(f"⚠️  Error processing job {task_id}: {e}")
        
        print(f"\n🎉 Cleaned up {cleaned_count} stale pending jobs")
        
    except Exception as e:
        print(f"❌ Error cleaning up stale pending jobs: {e}")

def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python redis_cleanup.py status                    - Show Redis status")
        print("  python redis_cleanup.py cleanup-failed           - Clean up failed jobs")
        print("  python redis_cleanup.py cleanup-old [hours]      - Clean up old jobs (default: 24 hours)")
        print("  python redis_cleanup.py cleanup-stale [hours]    - Clean up stale pending jobs (default: 24 hours)")
        print("  python redis_cleanup.py cleanup-all              - Clean up all old/failed jobs")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "status":
        show_redis_status()
    
    elif command == "cleanup-failed":
        cleanup_failed_jobs()
    
    elif command == "cleanup-old":
        hours = int(sys.argv[2]) if len(sys.argv) > 2 else 24
        cleanup_old_jobs(hours=hours)
    
    elif command == "cleanup-stale":
        hours = int(sys.argv[2]) if len(sys.argv) > 2 else 24
        cleanup_stale_pending_jobs(hours=hours)
    
    elif command == "cleanup-all":
        print("🧹 CLEANING UP ALL OLD/FAILED JOBS")
        print("=" * 40)
        cleanup_failed_jobs(confirm=True)
        cleanup_old_jobs(confirm=True, hours=24)
        cleanup_stale_pending_jobs(confirm=True, hours=24)
        print("\n✅ All cleanup operations completed!")
    
    else:
        print(f"❌ Unknown command: {command}")
        sys.exit(1)

if __name__ == "__main__":
    main()
