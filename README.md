# NCR Upload API

A production-ready FastAPI application with Celery for robust background job processing, featuring automatic memory management, batch processing, and zero-downtime deployments.

## Features

- **🚀 Celery Background Processing**: Robust, scalable background job processing with Redis
- **🧠 Smart Memory Management**: Automatic memory monitoring and job throttling
- **📦 Batch Processing**: Process multiple jobs efficiently with memory-aware batching
- **🔄 Zero-Downtime Deployments**: Rolling updates without service interruption
- **📊 Real-time Monitoring**: Flower dashboard and comprehensive health checks
- **🛡️ Production Ready**: Docker containers, health checks, and automatic recovery
- **📁 File Processing**: Wasabi S3 downloads, validation, and SFTP uploads
- **⚡ High Performance**: Optimized for memory usage and concurrent processing

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
├── routes.py                  # API routes
├── celery_app.py              # Celery application configuration
├── tasks.py                   # Celery tasks with memory management
├── start_worker.py            # Celery worker startup script
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
- `GET /job-status/{task_id}` - Get job status by task ID
- `GET /health` - Health check endpoint
- `GET /jobs/active` - Get all active jobs

### Batch Processing

- `POST /process-batch` - Process multiple jobs in batch
- `GET /batch-status/{batch_id}` - Get batch processing status

### Monitoring

- `GET /memory-stats` - Memory usage statistics
- `GET /celery-stats` - Celery worker statistics

### API Documentation

Once the server is running, visit:
- **Swagger UI**: http://localhost:8001/docs
- **ReDoc**: http://localhost:8001/redoc
- **Flower Dashboard**: http://localhost:5555

## Usage

### Starting a Job

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

### Batch Processing

```bash
curl -X POST "http://localhost:8001/process-batch" \
     -H "Content-Type: application/json" \
     -d '[
       {
         "job_id": "job-1",
         "username": "user1",
         "campaign": "campaign1"
       },
       {
         "job_id": "job-2", 
         "username": "user2",
         "campaign": "campaign2"
       }
     ]'
```

### Checking Job Status

```bash
curl "http://localhost:8001/job-status/{task_id}"
```

### Memory Statistics

```bash
curl "http://localhost:8001/memory-stats"
```

### Health Check

```bash
curl "http://localhost:8001/health"
```

## Job Processing Flow

1. **Job Creation**: Client sends job request to `/process-job`
2. **Memory Check**: System checks available memory before accepting job
3. **Celery Task**: Job is queued in Celery with automatic retry logic
4. **File Retrieval**: Files are retrieved from database and Wasabi S3
5. **Structure Organization**: Files are organized according to business logic
6. **Validation**: Files are zipped and sent to validator API
7. **Upload**: If validation passes, files are uploaded to SFTP server
8. **Status Updates**: Real-time status updates via Redis
9. **Cleanup**: Temporary files are cleaned up automatically
10. **Memory Management**: Worker memory is monitored and managed

## Configuration

All configuration is managed through environment variables. See the `env_sample` file for all available options.

### Key Configuration Options

```env
# API Configuration
API_PORT=8001
API_HOST=0.0.0.0

# Redis Configuration  
REDIS_HOST=localhost
REDIS_PORT=6380

# Memory Management
MAX_MEMORY_USAGE_PERCENT=80
CELERY_WORKER_CONCURRENCY=4
CELERY_WORKER_MAX_MEMORY_PER_CHILD=200000

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
- **routes.py**: FastAPI route definitions
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
- **Job Throttling**: Automatic rejection of new jobs when memory usage > 80%
- **Worker Recycling**: Workers restart after 1000 tasks or 200MB memory usage
- **Batch Processing**: Memory-aware batch processing with dynamic concurrency

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

All errors are logged and job status is updated accordingly.

## Security Considerations

- Store sensitive credentials in environment variables
- Use proper CORS configuration for production
- Implement authentication/authorization as needed
- Secure SFTP and database connections
- Validate all input data
- Non-root container execution
- Network isolation with Docker

## Troubleshooting

### Common Issues

1. **Redis Connection Error**: Ensure Redis server is running on port 6380
2. **Database Connection Error**: Check database credentials and connectivity
3. **SFTP Connection Error**: Verify SFTP server credentials and network access
4. **File Download Error**: Check Wasabi S3 credentials and file permissions
5. **Memory Issues**: Check memory stats and adjust worker concurrency
6. **Celery Worker Issues**: Check worker logs and restart if needed

### Logs

```bash
# View application logs
docker-compose logs -f web

# View worker logs
docker-compose logs -f worker

# View all logs
docker-compose logs -f
```

### Debug Commands

```bash
# Check memory stats
curl http://localhost:8001/memory-stats

# Check Celery stats
curl http://localhost:8001/celery-stats

# Check health
curl http://localhost:8001/health

# Monitor system
./deploy.sh monitor
```

## License

[Add your license information here]
