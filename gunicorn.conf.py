"""
Gunicorn configuration for NCR Upload API
"""
import os
import multiprocessing

# Server socket
bind = f"0.0.0.0:{os.getenv('API_PORT', '8001')}"
backlog = 2048

# Worker processes
workers = int(os.getenv('GUNICORN_WORKERS', multiprocessing.cpu_count() * 2 + 1))
worker_class = os.getenv('GUNICORN_WORKER_CLASS', 'uvicorn.workers.UvicornWorker')
worker_connections = 1000
timeout = 120
keepalive = 2

# Restart workers after this many requests, to help prevent memory leaks
max_requests = 1000
max_requests_jitter = 100

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = 'ncr_upload_api'

# Server mechanics
daemon = False
pidfile = '/tmp/gunicorn.pid'
user = None
group = None
tmp_upload_dir = None

# SSL (if needed)
# keyfile = None
# certfile = None

# Worker process management
preload_app = True
reload = False

# Memory management
worker_tmp_dir = '/dev/shm'  # Use shared memory for better performance

# Security
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190
