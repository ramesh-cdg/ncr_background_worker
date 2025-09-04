#!/usr/bin/env python3
"""
Test script to debug a specific job with detailed logging
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from tasks import process_job_task
from database import DatabaseManager
from redis_manager import redis_manager
import uuid

def test_job_processing(job_id: str, username: str = "test_user", campaign: str = "test_campaign", row_id: int = None):
    """Test job processing with detailed logging"""
    
    print("🧪 TESTING JOB PROCESSING")
    print("=" * 60)
    print(f"Job ID: {job_id}")
    print(f"Username: {username}")
    print(f"Campaign: {campaign}")
    print(f"Row ID: {row_id}")
    print()
    
    # First, let's check what the database returns
    print("1. 🔍 CHECKING DATABASE DIRECTLY")
    print("-" * 40)
    try:
        file_paths, sku_id = DatabaseManager.get_file_paths_from_db(job_id)
        print(f"✅ Database query successful")
        print(f"   - File paths count: {len(file_paths) if file_paths else 0}")
        print(f"   - SKU ID: {sku_id}")
        
        if file_paths:
            print(f"   - First 5 file paths:")
            for i, path in enumerate(file_paths[:5]):
                print(f"     {i+1}. {path}")
        else:
            print("   ❌ No file paths returned!")
            return False
            
    except Exception as e:
        print(f"❌ Database query failed: {e}")
        return False
    
    print()
    print("2. 🚀 RUNNING CELERY TASK")
    print("-" * 40)
    
    try:
        # Run the task directly (not through Celery queue)
        result = process_job_task(
            job_id=job_id,
            username=username,
            campaign=campaign,
            row_id=row_id
        )
        
        print(f"✅ Task completed")
        print(f"   - Result: {result}")
        return True
        
    except Exception as e:
        print(f"❌ Task failed: {e}")
        print(f"   - Exception type: {type(e).__name__}")
        return False

def test_celery_task(job_id: str, username: str = "test_user", campaign: str = "test_campaign", row_id: int = None):
    """Test job processing through Celery queue"""
    
    print("🧪 TESTING CELERY TASK")
    print("=" * 60)
    print(f"Job ID: {job_id}")
    print(f"Username: {username}")
    print(f"Campaign: {campaign}")
    print(f"Row ID: {row_id}")
    print()
    
    try:
        # Submit task to Celery
        task_result = process_job_task.delay(
            job_id=job_id,
            username=username,
            campaign=campaign,
            row_id=row_id
        )
        
        print(f"✅ Task submitted to Celery")
        print(f"   - Task ID: {task_result.id}")
        print(f"   - Waiting for result...")
        
        # Wait for result (with timeout)
        result = task_result.get(timeout=300)  # 5 minutes timeout
        
        print(f"✅ Task completed")
        print(f"   - Result: {result}")
        return True
        
    except Exception as e:
        print(f"❌ Celery task failed: {e}")
        print(f"   - Exception type: {type(e).__name__}")
        return False

def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python test_job_debug.py <job_id> [username] [campaign] [row_id]")
        print("  python test_job_debug.py <job_id> --celery [username] [campaign] [row_id]")
        print()
        print("Examples:")
        print("  python test_job_debug.py 12345")
        print("  python test_job_debug.py 12345 test_user test_campaign 67890")
        print("  python test_job_debug.py 12345 --celery test_user test_campaign 67890")
        sys.exit(1)
    
    job_id = sys.argv[1]
    use_celery = "--celery" in sys.argv
    
    # Parse optional arguments
    username = "test_user"
    campaign = "test_campaign"
    row_id = None
    
    if use_celery:
        # Remove --celery from args
        args = [arg for arg in sys.argv[2:] if arg != "--celery"]
    else:
        args = sys.argv[2:]
    
    if len(args) >= 1:
        username = args[0]
    if len(args) >= 2:
        campaign = args[1]
    if len(args) >= 3:
        try:
            row_id = int(args[2])
        except ValueError:
            print(f"⚠️ Invalid row_id: {args[2]}, using None")
    
    if use_celery:
        success = test_celery_task(job_id, username, campaign, row_id)
    else:
        success = test_job_processing(job_id, username, campaign, row_id)
    
    if success:
        print("\n🎉 Test completed successfully!")
    else:
        print("\n❌ Test failed!")
        sys.exit(1)

if __name__ == "__main__":
    main()
