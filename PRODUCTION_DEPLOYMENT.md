# Production Deployment Guide

## Overview

This guide covers deploying the NCR Upload API with Celery in production using Docker Compose with zero-downtime updates.

## Architecture

- **FastAPI App**: Runs on port 8001 with 4 Gunicorn workers
- **Redis**: Runs on port 6380 (external), 6379 (internal)
- **Celery Workers**: 4 background workers with smart queueing
- **Celery Beat**: Task scheduler
- **Flower**: Monitoring dashboard on port 5555

### Key Features

- **Smart Queueing**: Always accepts jobs, Celery manages concurrency
- **Memory Management**: Automatic worker recycling and memory monitoring
- **Zero-Downtime Deployments**: Rolling updates without service interruption
- **Health Monitoring**: Comprehensive health checks and monitoring

## Prerequisites

1. **Docker & Docker Compose** installed (latest version)
2. **Environment file** configured
3. **External database** accessible (MySQL/PostgreSQL)
4. **SFTP server** accessible

### Docker Compose Requirements

Ensure you have the latest Docker Compose installed:

```bash
# Check Docker Compose version
docker compose version

# Should show version 2.x or higher
```

## Quick Start

### 1. Setup Environment

```bash
# Copy environment template
cp env_sample .env

# Edit .env with your production credentials
nano .env
```

### 2. Deploy

```bash
# Make deploy script executable
chmod +x deploy.sh

# Deploy with zero-downtime updates
./deploy.sh deploy
```

### 3. Monitor

```bash
# Monitor system status
./deploy.sh monitor

# Check health
./deploy.sh health
```

## Production Configuration

### Environment Variables (.env)

```env
# API Configuration
API_PORT=8001
API_HOST=0.0.0.0

# Redis Configuration
REDIS_HOST=localhost
REDIS_PORT=6380

# Database Configuration (External)
DB_HOST=your-db-host
DB_USER=your-db-user
DB_PASS=your-db-password
DB_NAME=your-db-name

# SFTP Configuration
SFTP_HOST=your-sftp-host
SFTP_USERNAME=your-sftp-user
SFTP_PASSWORD=your-sftp-password

# Wasabi S3 Configuration
WASABI_ACCESS_KEY=your-access-key
WASABI_SECRET_KEY=your-secret-key

# Memory Management
MAX_MEMORY_USAGE_PERCENT=80
CELERY_WORKER_CONCURRENCY=4
CELERY_WORKER_MAX_MEMORY_PER_CHILD=200000
```

### Docker Compose Services

- **web**: FastAPI application with Gunicorn (1 instance, 1GB memory limit)
- **worker**: Celery workers (1 instance, 1GB memory limit)
- **beat**: Celery scheduler (1 instance, 256MB memory limit)
- **flower**: Monitoring dashboard (1 instance, 256MB memory limit)
- **redis**: Message broker (1 instance, 1GB memory limit)

### Modern Docker Compose Features

- **Resource Limits**: Memory limits and reservations for all services
- **Health Checks**: Comprehensive health monitoring with start periods
- **Build Context**: Explicit build context and dockerfile specification
- **Redis Optimization**: Memory management and LRU eviction policy
- **Latest Syntax**: Uses modern Docker Compose commands and features

## Zero-Downtime Deployment

The deployment script provides zero-downtime updates:

```bash
# Deploy new version
./deploy.sh deploy

# Rollback if needed
./deploy.sh rollback
```

### Deployment Process

1. **Pull latest images**
2. **Build new containers**
3. **Create backup**
4. **Stop existing services**
5. **Start new services**
6. **Health checks**
7. **Cleanup old containers**

## Memory Management

### Automatic Memory Monitoring

- **Memory checks** every 30 seconds
- **Smart queueing** - jobs always accepted and queued
- **Worker recycling** after 1000 tasks or 200MB memory usage
- **Concurrency control** - Celery manages worker capacity

### Memory Configuration

```env
# Maximum memory usage for monitoring
MAX_MEMORY_USAGE_PERCENT=80

# Worker memory limits
CELERY_WORKER_MAX_MEMORY_PER_CHILD=200000  # 200MB in KB
CELERY_WORKER_MAX_TASKS_PER_CHILD=1000

# Concurrency settings
CELERY_WORKER_CONCURRENCY=4
CELERY_WORKER_PREFETCH_MULTIPLIER=1

# Gunicorn settings
GUNICORN_WORKERS=4
GUNICORN_WORKER_CLASS=uvicorn.workers.UvicornWorker

# Task timeouts
CELERY_TASK_SOFT_TIME_LIMIT=3600  # 1 hour
CELERY_TASK_TIME_LIMIT=3900       # 1 hour 5 minutes
```

## Monitoring & Health Checks

### Health Endpoints

- `GET /health` - Overall system health
- `GET /memory-stats` - Memory usage statistics
- `GET /celery-stats` - Celery worker statistics
- `GET /jobs/active` - Active job status

### Flower Dashboard

Access monitoring at: `http://your-server:5555`

Features:
- Real-time task monitoring
- Worker statistics
- Task history
- Queue management

### Logs

```bash
# View application logs
docker-compose logs -f web

# View worker logs
docker-compose logs -f worker

# View all logs
docker-compose logs -f
```

## Scaling

### Horizontal Scaling

```bash
# Scale web instances
docker-compose up -d --scale web=4

# Scale workers
docker-compose up -d --scale worker=6
```

### Vertical Scaling

Update `.env`:
```env
CELERY_WORKER_CONCURRENCY=8
CELERY_WORKER_MAX_MEMORY_PER_CHILD=400000
```

## Backup & Recovery

### Automatic Backups

Backups are created during deployment:
- Database dumps
- Redis snapshots
- Configuration files

### Manual Backup

```bash
# Create backup
./deploy.sh backup

# Backup location
ls -la backups/
```

### Recovery

```bash
# Rollback to previous version
./deploy.sh rollback
```

## Security

### Network Security

- Redis on non-standard port (6380)
- Internal container communication
- No external database exposure

### Application Security

- Non-root container user
- Environment variable secrets
- Health check endpoints
- Rate limiting (if using reverse proxy)

## Performance Tuning

### Redis Optimization

```env
# Redis configuration in docker-compose.yml
command: redis-server --appendonly yes --maxmemory 1gb --maxmemory-policy allkeys-lru
```

### Worker Optimization

```env
# Optimize for your workload
CELERY_WORKER_CONCURRENCY=4
CELERY_WORKER_PREFETCH_MULTIPLIER=1
CELERY_WORKER_MAX_TASKS_PER_CHILD=1000
```

### Memory Optimization

```env
# Adjust based on server specs
MAX_MEMORY_USAGE_PERCENT=80
CELERY_WORKER_MAX_MEMORY_PER_CHILD=200000
```

## Troubleshooting

### Common Issues

1. **Memory Issues**
   ```bash
   # Check memory stats
   curl http://localhost:8001/memory-stats
   
   # Scale down if needed
   docker-compose up -d --scale worker=1
   ```

2. **Redis Connection Issues**
   ```bash
   # Check Redis status
   docker-compose logs redis
   
   # Test connection
   docker-compose exec redis redis-cli ping
   ```

3. **Worker Issues**
   ```bash
   # Check worker status
   docker-compose logs worker
   
   # Restart workers
   docker-compose restart worker
   ```

### Debug Mode

```bash
# Run in debug mode
CELERY_LOGLEVEL=debug docker compose up worker
```

## Logging & Monitoring

### Viewing Logs

#### Real-time Log Monitoring

```bash
# Monitor all services
docker compose logs -f

# Monitor specific services
docker compose logs -f web      # FastAPI + Gunicorn
docker compose logs -f worker   # Celery workers
docker compose logs -f beat     # Celery beat scheduler
docker compose logs -f flower   # Flower monitoring
docker compose logs -f redis    # Redis server
```

#### Log Analysis

```bash
# View logs with timestamps
docker compose logs -f -t

# View last N lines
docker compose logs --tail=100 web
docker compose logs --tail=50 worker

# Filter by log level
docker compose logs -f web | grep "ERROR"
docker compose logs -f worker | grep -E "(ERROR|CRITICAL|WARNING)"

# Filter by time/date
docker compose logs -f web | grep "2024-01-15"
docker compose logs -f worker | grep "14:30"
```

#### Individual Container Logs

```bash
# Get container names
docker compose ps

# View specific container logs
docker logs -f ncr_background_worker-web-1
docker logs -f ncr_background_worker-worker-1
docker logs -f ncr_redis

# View with timestamps
docker logs -f -t ncr_background_worker-web-1
```

### Log Levels

#### Application Logs (FastAPI/Gunicorn)
- **INFO**: General application flow
- **WARNING**: Non-critical issues
- **ERROR**: Application errors
- **DEBUG**: Detailed debugging information

#### Celery Worker Logs
- **INFO**: Task processing status
- **WARNING**: Memory warnings, retries
- **ERROR**: Task failures, connection issues
- **DEBUG**: Detailed task execution

#### Redis Logs
- **INFO**: Connection status, operations
- **WARNING**: Memory usage warnings
- **ERROR**: Connection failures

### Log Rotation

```bash
# Configure log rotation (add to docker-compose.yml)
services:
  web:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

### Monitoring Commands

```bash
# Check service status
docker compose ps

# Check resource usage
docker stats

# Check health endpoints
curl http://localhost:8001/health
curl http://localhost:8001/memory-stats
curl http://localhost:8001/celery-stats

# Monitor Flower dashboard
open http://localhost:5555
```

## Maintenance

### Regular Tasks

1. **Monitor memory usage**
2. **Check worker health**
3. **Review logs for errors**
4. **Update dependencies**
5. **Clean up old backups**

### Updates

```bash
# Update application
git pull
./deploy.sh deploy

# Update dependencies
docker-compose build --no-cache
./deploy.sh deploy
```

## Production Checklist

- [ ] Environment variables configured
- [ ] External database accessible
- [ ] SFTP server accessible
- [ ] Redis port 6380 available
- [ ] API port 8001 available
- [ ] Monitoring configured
- [ ] Backups working
- [ ] Health checks passing
- [ ] Memory limits appropriate
- [ ] Logging configured
- [ ] Security measures in place

## Support

For issues or questions:
1. Check logs: `docker-compose logs -f`
2. Check health: `./deploy.sh health`
3. Monitor resources: `./deploy.sh monitor`
4. Review this documentation
