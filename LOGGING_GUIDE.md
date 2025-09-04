# Logging Guide - NCR Upload API

## Quick Reference

### 🚀 Most Common Commands

```bash
# View all logs in real-time
docker compose logs -f

# View specific service logs
docker compose logs -f web      # FastAPI + Gunicorn
docker compose logs -f worker   # Celery workers
docker compose logs -f redis    # Redis server

# View last 100 lines
docker compose logs --tail=100 web
```

### 🔍 Troubleshooting Commands

```bash
# Check for errors
docker compose logs -f web | grep "ERROR"
docker compose logs -f worker | grep "ERROR"

# Check memory issues
docker compose logs -f worker | grep -i "memory"
docker compose logs -f worker | grep -i "killed"

# Check connection issues
docker compose logs -f worker | grep -i "connection"
docker compose logs -f web | grep -i "redis"
```

### 📊 Service-Specific Logs

#### FastAPI Web Service (Gunicorn)
```bash
# View web service logs
docker compose logs -f web

# Filter for specific endpoints
docker compose logs -f web | grep "POST /process-job"
docker compose logs -f web | grep "GET /health"

# Check Gunicorn worker status
docker compose logs -f web | grep "worker"
```

#### Celery Workers
```bash
# View worker logs
docker compose logs -f worker

# Check task processing
docker compose logs -f worker | grep "process_job_task"
docker compose logs -f worker | grep "SUCCESS"
docker compose logs -f worker | grep "FAILED"

# Check memory management
docker compose logs -f worker | grep "memory"
docker compose logs -f worker | grep "recycling"
```

#### Redis Server
```bash
# View Redis logs
docker compose logs -f redis

# Check Redis operations
docker compose logs -f redis | grep "connected"
docker compose logs -f redis | grep "memory"
```

#### Celery Beat Scheduler
```bash
# View beat scheduler logs
docker compose logs -f beat

# Check scheduled tasks
docker compose logs -f beat | grep "Scheduler"
```

#### Flower Monitoring
```bash
# View Flower logs
docker compose logs -f flower

# Check monitoring status
docker compose logs -f flower | grep "started"
```

### 🕐 Time-Based Log Filtering

```bash
# Filter by date
docker compose logs -f web | grep "2024-01-15"

# Filter by time
docker compose logs -f worker | grep "14:30"

# Filter by time range (last hour)
docker compose logs --since="1h" web
```

### 📈 Log Analysis

#### Performance Monitoring
```bash
# Check response times
docker compose logs -f web | grep "ms"

# Check memory usage
docker compose logs -f worker | grep "memory_percent"

# Check task duration
docker compose logs -f worker | grep "completed in"
```

#### Error Analysis
```bash
# Count errors by service
docker compose logs web | grep -c "ERROR"
docker compose logs worker | grep -c "ERROR"

# Get error details
docker compose logs worker | grep -A 5 "ERROR"
```

### 🔧 Debug Mode

#### Enable Debug Logging
```bash
# Run worker in debug mode
CELERY_LOGLEVEL=debug docker compose up worker

# Run web service in debug mode
GUNICORN_LOGLEVEL=debug docker compose up web
```

#### Verbose Logging
```bash
# Enable verbose Celery logging
docker compose logs -f worker | grep -v "INFO"

# Show only warnings and errors
docker compose logs -f web | grep -E "(WARNING|ERROR|CRITICAL)"
```

### 📋 Log Export

#### Save Logs to File
```bash
# Export all logs
docker compose logs > all_logs.txt

# Export specific service logs
docker compose logs web > web_logs.txt
docker compose logs worker > worker_logs.txt

# Export with timestamps
docker compose logs -t > timestamped_logs.txt
```

#### Log Rotation
```bash
# Check log file sizes
docker system df

# Clean up old logs
docker system prune -f
```

### 🚨 Emergency Debugging

#### When Services Won't Start
```bash
# Check container status
docker compose ps

# Check container logs
docker logs ncr_background_worker-web-1
docker logs ncr_background_worker-worker-1

# Check system resources
docker stats
```

#### When Jobs Are Failing
```bash
# Check worker errors
docker compose logs -f worker | grep -A 10 "FAILED"

# Check memory issues
docker compose logs -f worker | grep -i "memory"

# Check Redis connection
docker compose logs -f redis | grep -i "error"
```

#### When API Is Slow
```bash
# Check web service performance
docker compose logs -f web | grep "ms"

# Check worker queue
docker compose logs -f worker | grep "queue"

# Check memory usage
curl http://localhost:8001/memory-stats
```

### 📱 Monitoring Dashboard

#### Flower Dashboard
```bash
# Access Flower monitoring
open http://localhost:5555

# Check Flower logs
docker compose logs -f flower
```

#### Health Endpoints
```bash
# Check overall health
curl http://localhost:8001/health

# Check memory stats
curl http://localhost:8001/memory-stats

# Check Celery stats
curl http://localhost:8001/celery-stats
```

### 🔄 Log Rotation Configuration

Add to `docker-compose.yml`:

```yaml
services:
  web:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
  
  worker:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

### 💡 Pro Tips

1. **Use `-f` flag** for real-time log following
2. **Use `--tail=N`** to see last N lines
3. **Use `-t` flag** for timestamps
4. **Use `grep`** to filter specific information
5. **Use `|` pipe** to combine commands
6. **Use `>` to save** logs to files
7. **Use `docker stats`** to monitor resource usage
8. **Use Flower dashboard** for visual monitoring

### 🆘 Quick Troubleshooting

| Issue | Command |
|-------|---------|
| Service won't start | `docker compose ps` |
| Jobs failing | `docker compose logs -f worker \| grep ERROR` |
| Memory issues | `docker compose logs -f worker \| grep -i memory` |
| Connection issues | `docker compose logs -f \| grep -i connection` |
| Performance issues | `docker stats` |
| API errors | `docker compose logs -f web \| grep ERROR` |
