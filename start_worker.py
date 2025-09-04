#!/usr/bin/env python3
"""
Celery worker startup script with memory management
"""
import os
import sys
import subprocess
import argparse
from config import settings


def start_celery_worker(concurrency=None, queues=None, loglevel='info'):
    """Start Celery worker with specified configuration"""
    
    # Default concurrency based on memory
    if concurrency is None:
        concurrency = settings.celery_worker_concurrency
    
    # Default queues
    if queues is None:
        queues = ['default', 'job_processing', 'batch_processing', 'monitoring']
    
    # Build Celery worker command
    cmd = [
        'celery',
        '-A', 'celery_app',
        'worker',
        '--loglevel', loglevel,
        '--concurrency', str(concurrency),
        '--queues', ','.join(queues),
        '--prefetch-multiplier', str(settings.celery_worker_prefetch_multiplier),
        '--max-tasks-per-child', str(settings.celery_worker_max_tasks_per_child),
        '--max-memory-per-child', str(settings.celery_worker_max_memory_per_child),
        '--time-limit', str(settings.celery_task_time_limit),
        '--soft-time-limit', str(settings.celery_task_soft_time_limit),
        '--without-gossip',
        '--without-mingle',
        '--without-heartbeat'
    ]
    
    print(f"Starting Celery worker with:")
    print(f"  Concurrency: {concurrency}")
    print(f"  Queues: {', '.join(queues)}")
    print(f"  Log Level: {loglevel}")
    print(f"  Max Memory per Child: {settings.celery_worker_max_memory_per_child}KB")
    print(f"  Max Tasks per Child: {settings.celery_worker_max_tasks_per_child}")
    print(f"  Time Limit: {settings.celery_task_time_limit}s")
    print(f"  Soft Time Limit: {settings.celery_task_soft_time_limit}s")
    print()
    
    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        print("\nShutting down Celery worker...")
    except subprocess.CalledProcessError as e:
        print(f"Error starting Celery worker: {e}")
        sys.exit(1)


def start_celery_beat():
    """Start Celery beat scheduler"""
    cmd = [
        'celery',
        '-A', 'celery_app',
        'beat',
        '--loglevel', 'info'
    ]
    
    print("Starting Celery beat scheduler...")
    
    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        print("\nShutting down Celery beat...")
    except subprocess.CalledProcessError as e:
        print(f"Error starting Celery beat: {e}")
        sys.exit(1)


def start_flower():
    """Start Flower monitoring"""
    cmd = [
        'celery',
        '-A', 'celery_app',
        'flower',
        '--port', '5555',
        '--broker', settings.celery_broker_url
    ]
    
    print("Starting Flower monitoring on http://localhost:5555")
    
    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        print("\nShutting down Flower...")
    except subprocess.CalledProcessError as e:
        print(f"Error starting Flower: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description='Start Celery components')
    parser.add_argument('component', choices=['worker', 'beat', 'flower', 'all'],
                       help='Component to start')
    parser.add_argument('--concurrency', type=int, default=None,
                       help='Number of worker processes')
    parser.add_argument('--queues', nargs='+', default=None,
                       help='Queues to process')
    parser.add_argument('--loglevel', default='info',
                       choices=['debug', 'info', 'warning', 'error'],
                       help='Log level')
    
    args = parser.parse_args()
    
    if args.component == 'worker':
        start_celery_worker(args.concurrency, args.queues, args.loglevel)
    elif args.component == 'beat':
        start_celery_beat()
    elif args.component == 'flower':
        start_flower()
    elif args.component == 'all':
        print("Starting all Celery components...")
        print("Note: Run each component in a separate terminal for production")
        print()
        
        # Start worker
        print("1. Starting worker...")
        start_celery_worker(args.concurrency, args.queues, args.loglevel)


if __name__ == '__main__':
    main()
