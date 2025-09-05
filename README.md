# NCR Upload API

A production-ready FastAPI application with Celery for robust background job processing, featuring intelligent queueing, automatic memory management, and zero-downtime deployments.

## Features

- **🚀 Celery Background Processing**: Robust, scalable background job processing with Redis
- **📋 Smart Queueing**: Always accepts jobs - Celery handles concurrency and memory management
- **🧠 Automatic Memory Management**: Built-in memory monitoring and worker recycling
- **📦 Batch Processing**: Process multiple jobs efficiently with memory-aware batching
- **🔄 Zero-Downtime Deployments**: Rolling updates without service interruption
- **📊 Real-time Monitoring**: Flower dashboard and comprehensive health checks
- **🛡️ Production Ready**: Docker containers, health checks, and automatic recovery
- **📁 File Processing**: Wasabi S3 downloads, validation, and SFTP uploads
- **⚡ High Performance**: Gunicorn workers with optimized concurrency control
- **🧹 Clean Redis**: No historical data accumulation - only active tasks

## Project Structure

```
ncr_background_worker/
├── main.py                    # Main FastAPI application
├── config.py                  # Configuration management
├── models.py                  # Pydantic models
├── database.py                # Database operations
├── sftp_client.py             # SFTP operations
├── redis_manager.py           # Redis job management
├── file_processor.py          # File processing utilities
├── validation_service.py      # Validation service
├── routes.py                  # API routes (simplified)
├── celery_app.py              # Celery application configuration
├── tasks.py                   # Celery tasks with memory management
├── start_worker.py            # Celery worker startup script
├── gunicorn.conf.py           # Gunicorn configuration
├── docker-compose.yml         # Production Docker setup
├── Dockerfile                 # Application container
├── deploy.sh                  # Zero-downtime deployment script
├── requirements.txt           # Python dependencies
├── env_sample                 # Environment template
├── PRODUCTION_DEPLOYMENT.md   # Production deployment guide
└── README.md                  # This file
```

## Prerequisites

- **Docker & Docker Compose** (latest version)
- **Python 3.8+** (for development)
- **Redis server** (port 6380)
- **External database** (MySQL/PostgreSQL)
- **SFTP server access**
- **Wasabi S3 credentials**

## Quick Start (Production)

### 1. Setup Environment

```bash
# Copy environment template
cp env_sample .env

# Edit with your credentials
nano .env
```

### 2. Deploy with Docker

```bash
# Make deploy script executable
chmod +x deploy.sh

# Deploy with zero-downtime updates
./deploy.sh deploy
```

### 3. Access Services

- **API**: http://localhost:8001
- **API Docs**: http://localhost:8001/docs
- **Flower Monitoring**: http://localhost:5555
- **Redis**: localhost:6380

### 4. Architecture Overview

The application uses a modern microservices architecture:

- **FastAPI Web Service**: 4 Gunicorn workers handling HTTP requests
- **Celery Workers**: 4 background workers processing jobs
- **Redis**: Message broker and job queue storage (no historical data)
- **Smart Queueing**: Always accepts jobs, Celery manages concurrency

## Development Setup

### 1. Local Development

```bash
# Clone repository
git clone <repository-url>
cd ncr_background_worker

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Setup environment
cp env_sample .env
# Edit .env with your credentials

# Start Redis (port 6380)
redis-server --port 6380

# Start Celery worker
python start_worker.py worker

# Start Celery beat (in another terminal)
python start_worker.py beat

# Start Flower monitoring (in another terminal)
python start_worker.py flower

# Start FastAPI app
python main.py
```

## API Endpoints

### Core Endpoints

- `GET /` - Root endpoint with API information
- `POST /process-job` - Start a new job processing
- `GET /job-status/{job_id}/{username}` - Get job status by job_id and username
- `GET /running-tasks` - Get all running tasks
- `GET /health` - Health check endpoint

### Batch Processing

- `POST /process-batch` - Process multiple jobs in batch
- `GET /batch-status/{username}` - Get batch processing status by username

### System Management

- `POST /redis/reset` - Reset all Redis data (requires password)
- `GET /memory-stats` - Memory usage statistics
- `GET /celery-stats` - Celery worker statistics
- `GET /redis-stats` - Redis statistics

### API Documentation

Once the server is running, visit:
- **Swagger UI**: http://localhost:8001/docs
- **ReDoc**: http://localhost:8001/redoc
- **Flower Dashboard**: http://localhost:5555

## Usage

### Starting a Single Job

```bash
curl -X POST "http://localhost:8001/process-job" \
     -H "Content-Type: application/json" \
     -d '{
       "job_id": "your-job-id",
       "username": "your-username",
       "campaign": "your-campaign",
       "row_id": 123
     }'
```

**Response:**
```json
{
  "job_id": "your-job-id",
  "status": "processing",
  "message": "Job processing started",
  "timestamp": "2024-01-15T10:30:00",
  "task_id": "uuid-task-id"
}
```

### Getting Job Status

```bash
curl "http://localhost:8001/job-status/your-job-id/your-username"
```

**Response:**
```json
{
  "job_id": "your-job-id",
  "username": "your-username",
  "task_id": "uuid-task-id",
  "status": "processing",
  "message": "Processing files...",
  "campaign": "your-campaign",
  "row_id": 123,
  "timestamp": "2024-01-15T10:30:00"
}
```

### Getting All Running Tasks

```bash
curl "http://localhost:8001/running-tasks"
```

**Response:**
```json
{
  "running_tasks": [
    {
      "job_id": "job-1",
      "username": "user1",
      "status": "processing",
      "message": "Processing files..."
    }
  ],
  "count": 1,
  "timestamp": "2024-01-15T10:30:00"
}
```

### Batch Processing

```bash
curl -X POST "http://localhost:8001/process-batch" \
     -H "Content-Type: application/json" \
     -d '[
       {
         "job_id": "job-1",
         "username": "user1",
         "campaign": "campaign1",
         "row_id": 1
       },
       {
         "job_id": "job-2", 
         "username": "user1",
         "campaign": "campaign1",
         "row_id": 2
       }
     ]'
```

**Response:**
```json
{
  "batch_id": "batch-uuid",
  "total_jobs": 2,
  "common_username": "user1",
  "status": "processing",
  "message": "Batch processing started for 2 jobs with username 'user1'",
  "timestamp": "2024-01-15T10:30:00"
}
```

### Getting Batch Status

```bash
curl "http://localhost:8001/batch-status/user1"
```

**Response:**
```json
{
  "username": "user1",
  "batch_id": "batch-uuid",
  "status": "processing",
  "total_jobs": 2,
  "individual_results": [
    {
      "job_id": "job-1",
      "task_id": "task-uuid-1",
      "status": "processing",
      "result": null
    },
    {
      "job_id": "job-2",
      "task_id": "task-uuid-2", 
      "status": "completed",
      "result": {"status": "completed", "validation_result": "passed"}
    }
  ],
  "completed_jobs": 1,
  "failed_jobs": 0,
  "processing_jobs": 1,
  "timestamp": "2024-01-15T10:30:00"
}
```

### Resetting Redis Data

```bash
curl -X POST "http://localhost:8001/redis/reset" \
     -H "Content-Type: application/json" \
     -d '{"password": "reset@2025"}'
```

**Response:**
```json
{
  "status": "success",
  "message": "Redis data reset successfully - deleted 15 keys",
  "deleted_keys": 15,
  "timestamp": "2024-01-15T10:30:00"
}
```

## Job Processing Flow

1. **Job Creation**: Client sends job request to `/process-job`
2. **Immediate Queueing**: Job is always accepted and queued in Redis
3. **Celery Processing**: Worker picks up job when available (concurrency controlled)
4. **File Retrieval**: Files are retrieved from database and Wasabi S3
5. **Structure Organization**: Files are organized according to business logic
6. **Validation**: Files are zipped and sent to validator API
7. **Upload Decision**: 
   - If validation passes: Files are uploaded to SFTP server
   - If validation fails: Files are NOT uploaded, task completes with failed validation
8. **Status Updates**: Real-time status updates via Redis
9. **Cleanup**: Temporary files are cleaned up automatically
10. **Redis Cleanup**: Completed/failed tasks are immediately removed from Redis (no historical data)

## Configuration

All configuration is managed through environment variables. See the `env_sample` file for all available options.

### Key Configuration Options

```env
# API Configuration
API_PORT=8001
API_HOST=0.0.0.0

# Gunicorn Configuration
GUNICORN_WORKERS=4
GUNICORN_WORKER_CLASS=uvicorn.workers.UvicornWorker
GUNICORN_TIMEOUT=120

# Redis Configuration  
REDIS_HOST=redis
REDIS_PORT=6379

# Celery Configuration
CELERY_WORKER_CONCURRENCY=4
CELERY_WORKER_PREFETCH_MULTIPLIER=1
CELERY_WORKER_MAX_MEMORY_PER_CHILD=200000
CELERY_WORKER_MAX_TASKS_PER_CHILD=1000

# Memory Management
MAX_MEMORY_USAGE_PERCENT=80

# Batch Processing
BATCH_SIZE=5
BATCH_TIMEOUT=300
```

## Production Deployment

For detailed production deployment instructions, see [PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md).

### Quick Production Commands

```bash
# Deploy with zero-downtime updates
./deploy.sh deploy

# Monitor system status
./deploy.sh monitor

# Check health
./deploy.sh health

# Rollback if needed
./deploy.sh rollback
```

## Development

### Running in Development Mode

The application includes auto-reload for development:

```bash
python main.py
```

### Code Structure

- **config.py**: Centralized configuration management
- **models.py**: Pydantic models for request/response validation
- **database.py**: Database operations and connection management
- **sftp_client.py**: SFTP operations and file upload
- **redis_manager.py**: Redis operations and job status management
- **file_processor.py**: File processing utilities and Wasabi S3 operations
- **validation_service.py**: External validation API integration
- **celery_app.py**: Celery application configuration
- **tasks.py**: Celery tasks with memory management
- **routes.py**: FastAPI route definitions (simplified API)
- **main.py**: Application entry point and configuration

## Monitoring

### Health Check

The `/health` endpoint provides:
- Overall service status
- Redis connection status
- Database connection status
- Current timestamp

### Memory Monitoring

The `/memory-stats` endpoint provides:
- Process memory usage
- System memory usage
- Recommended concurrency
- Job acceptance status

### Celery Monitoring

The `/celery-stats` endpoint provides:
- Active tasks
- Scheduled tasks
- Worker statistics
- Queue information

### Redis Statistics

The `/redis-stats` endpoint provides:
- Redis memory usage
- Connected clients
- Job counts (only active tasks)
- Keyspace statistics

### Flower Dashboard

Access real-time monitoring at: http://localhost:5555

Features:
- Task monitoring
- Worker statistics
- Queue management
- Task history

## Memory Management

### Automatic Features

- **Memory Monitoring**: Continuous monitoring of system and process memory
- **Smart Queueing**: Jobs are always accepted and queued, processed when memory is available
- **Worker Recycling**: Workers restart after 1000 tasks or 200MB memory usage
- **Concurrency Control**: Celery manages worker concurrency based on system capacity
- **Batch Processing**: Memory-aware batch processing with dynamic concurrency
- **Clean Redis**: No historical data accumulation - only active tasks stored

### Configuration

```env
# Memory limits
MAX_MEMORY_USAGE_PERCENT=80
CELERY_WORKER_MAX_MEMORY_PER_CHILD=200000

# Worker settings
CELERY_WORKER_CONCURRENCY=4
CELERY_WORKER_MAX_TASKS_PER_CHILD=1000
```

## Error Handling

The application includes comprehensive error handling:
- Database connection errors
- SFTP connection errors
- Redis connection errors
- File processing errors
- Validation API errors
- Memory management errors
- Celery task errors

All errors are logged and job status is updated accordingly. Failed tasks are immediately removed from Redis.

## Security Considerations

- Store sensitive credentials in environment variables
- Use proper CORS configuration for production
- Implement authentication/authorization as needed
- Secure SFTP and database connections
- Validate all input data
- Non-root container execution
- Network isolation with Docker
- Redis reset endpoint requires password protection

## Troubleshooting

### Common Issues

1. **Redis Connection Error**: Ensure Redis server is running on port 6380
2. **Database Connection Error**: Check database credentials and connectivity
3. **SFTP Connection Error**: Verify SFTP server credentials and network access
4. **File Download Error**: Check Wasabi S3 credentials and file permissions
5. **Memory Issues**: Check memory stats and adjust worker concurrency
6. **Celery Worker Issues**: Check worker logs and restart if needed
7. **Gunicorn Issues**: Check Gunicorn configuration and worker processes
8. **Port Conflicts**: Ensure ports 8001 and 6380 are available
9. **Job Not Found**: Completed/failed jobs are removed from Redis immediately

### Logs

#### Docker Compose Logs

```bash
# View application logs (FastAPI + Gunicorn)
docker compose logs -f web

# View worker logs (Celery workers)
docker compose logs -f worker

# View beat scheduler logs
docker compose logs -f beat

# View flower monitoring logs
docker compose logs -f flower

# View Redis logs
docker compose logs -f redis

# View all service logs
docker compose logs -f

# View logs with timestamps
docker compose logs -f -t

# View last 100 lines of logs
docker compose logs --tail=100 web
```

#### Individual Container Logs

```bash
# Get container names
docker compose ps

# View logs for specific container
docker logs -f ncr_background_worker-web-1
docker logs -f ncr_background_worker-worker-1
docker logs -f ncr_redis

# View logs with timestamps
docker logs -f -t ncr_background_worker-web-1

# View last 50 lines
docker logs --tail=50 ncr_background_worker-worker-1
```

#### Log Filtering

```bash
# Filter logs by service and time
docker compose logs -f web | grep "ERROR"
docker compose logs -f worker | grep "WARNING"
docker compose logs -f web | grep "2024-01-15"

# Filter by log level
docker compose logs -f worker | grep -E "(ERROR|CRITICAL)"
docker compose logs -f web | grep -E "(INFO|DEBUG)"
```

### Debug Commands

```bash
# Check memory stats
curl http://localhost:8001/memory-stats

# Check Celery stats
curl http://localhost:8001/celery-stats

# Check Redis stats
curl http://localhost:8001/redis-stats

# Check health
curl http://localhost:8001/health

# Check running tasks
curl http://localhost:8001/running-tasks

# Monitor system
./deploy.sh monitor
```

## License

[Add your license information here]