# Production Deployment Guide

## Overview

This guide covers deploying the NCR Upload API with Celery in production using Docker Compose with zero-downtime updates.

## Architecture

- **FastAPI App**: Runs on port 8001
- **Redis**: Runs on port 6380 (external), 6379 (internal)
- **Celery Workers**: Background job processing with memory management
- **Celery Beat**: Task scheduler
- **Flower**: Monitoring dashboard on port 5555

## Prerequisites

1. **Docker & Docker Compose** installed (V2 recommended, V1 supported)
2. **Environment file** configured
3. **External database** accessible (MySQL/PostgreSQL)
4. **SFTP server** accessible

### Docker Compose Version Check

Run the version check script to ensure compatibility:

```bash
chmod +x docker-compose-check.sh
./docker-compose-check.sh
```

This will detect and verify your Docker Compose installation.

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

- **web**: FastAPI application (2 replicas, 512MB memory limit)
- **worker**: Celery workers (2 replicas, 1GB memory limit)
- **beat**: Celery scheduler (1 instance, 256MB memory limit)
- **flower**: Monitoring dashboard (1 instance, 256MB memory limit)
- **redis**: Message broker (1 instance, 1GB memory limit)

### Modern Docker Compose Features

- **Resource Limits**: Memory limits and reservations for all services
- **Health Checks**: Comprehensive health monitoring with start periods
- **Build Context**: Explicit build context and dockerfile specification
- **Redis Optimization**: Memory management and LRU eviction policy
- **Compatibility**: Works with both Docker Compose V1 and V2

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
4. **Scale up new workers** (rolling update)
5. **Scale up new web instances** (rolling update)
6. **Scale down old instances**
7. **Health checks**

## Memory Management

### Automatic Memory Monitoring

- **Memory checks** every 30 seconds
- **Automatic scaling** based on available memory
- **Job rejection** when memory usage > 80%
- **Worker recycling** after 1000 tasks or 200MB memory

### Memory Configuration

```env
# Maximum memory usage before rejecting jobs
MAX_MEMORY_USAGE_PERCENT=80

# Worker memory limits
CELERY_WORKER_MAX_MEMORY_PER_CHILD=200000  # 200MB in KB
CELERY_WORKER_MAX_TASKS_PER_CHILD=1000

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
CELERY_LOGLEVEL=debug docker-compose up worker
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
