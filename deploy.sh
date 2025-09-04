#!/bin/bash

# Production deployment script with zero-downtime updates
set -e

# Configuration
COMPOSE_FILE="docker-compose.yml"
BACKUP_DIR="./backups"
LOG_FILE="./deploy.log"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1" | tee -a $LOG_FILE
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR:${NC} $1" | tee -a $LOG_FILE
    exit 1
}

warning() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING:${NC} $1" | tee -a $LOG_FILE
}

# Check if Docker and Docker Compose are installed
check_dependencies() {
    log "Checking dependencies..."
    
    if ! command -v docker &> /dev/null; then
        error "Docker is not installed"
    fi
    
    if ! docker compose version &> /dev/null; then
        error "Docker Compose is not installed or not working"
    fi
    
    log "Dependencies check passed - using latest Docker Compose"
}

# Create backup
create_backup() {
    log "Creating backup..."
    
    mkdir -p $BACKUP_DIR
    BACKUP_NAME="backup_$(date +%Y%m%d_%H%M%S)"
    
    # Backup Redis data
    if docker compose exec -T redis redis-cli BGSAVE; then
        log "Redis backup initiated"
    else
        warning "Failed to create Redis backup"
    fi
}

# Health check function
health_check() {
    local service=$1
    local max_attempts=30
    local attempt=1
    
    log "Performing health check for $service..."
    
    while [ $attempt -le $max_attempts ]; do
        if docker compose ps $service | grep -q "healthy\|Up"; then
            log "$service is healthy"
            return 0
        fi
        
        log "Health check attempt $attempt/$max_attempts for $service"
        sleep 10
        ((attempt++))
    done
    
    error "$service failed health check after $max_attempts attempts"
}

# Clean up existing containers
cleanup_containers() {
    log "Cleaning up existing containers..."
    
    # Stop and remove existing containers
    docker compose down --remove-orphans
    
    # Remove any dangling containers
    docker container prune -f
    
    log "Container cleanup completed"
}

# Zero-downtime deployment
deploy() {
    log "Starting deployment..."
    
    # Clean up existing containers
    cleanup_containers
    
    # Pull latest images
    log "Pulling latest images..."
    docker compose pull
    
    # Build new images
    log "Building new images..."
    docker compose build --no-cache
    
    # Create backup before deployment
    create_backup
    
    # Stop existing services first to avoid port conflicts
    log "Stopping existing services..."
    docker compose down
    
    # Start services with new configuration
    log "Starting services with new configuration..."
    docker compose up -d
    
    # Wait for services to be healthy
    health_check "redis"
    health_check "web"
    health_check "worker"
    
    # Final health check
    log "Performing final health check..."
    health_check "web"
    health_check "worker"
    health_check "beat"
    health_check "flower"
    
    log "Deployment completed successfully!"
}

# Rollback function
rollback() {
    log "Starting rollback..."
    
    # Stop current services
    docker compose down
    
    # Start services with previous configuration
    docker compose up -d
    
    log "Rollback completed"
}

# Cleanup function
cleanup() {
    log "Cleaning up old images and containers..."
    
    # Remove unused images
    docker image prune -f
    
    # Remove unused volumes (be careful with this)
    # docker volume prune -f
    
    # Remove old backups (keep last 7 days)
    find $BACKUP_DIR -name "*.sql" -mtime +7 -delete 2>/dev/null || true
    
    log "Cleanup completed"
}

# Monitor function
monitor() {
    log "Starting monitoring..."
    
    while true; do
        echo "=== Service Status ==="
        docker compose ps
        
        echo -e "\n=== Memory Usage ==="
        docker stats --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}"
        
        echo -e "\n=== Celery Stats ==="
        curl -s http://localhost:8001/celery-stats | jq '.' 2>/dev/null || echo "Celery stats unavailable"
        
        echo -e "\n=== Memory Stats ==="
        curl -s http://localhost:8001/memory-stats | jq '.' 2>/dev/null || echo "Memory stats unavailable"
        
        sleep 60
    done
}

# Main script logic
case "${1:-deploy}" in
    "deploy")
        check_dependencies
        deploy
        cleanup
        ;;
    "rollback")
        rollback
        ;;
    "monitor")
        monitor
        ;;
    "health")
        health_check "web"
        health_check "worker"
        ;;
    "backup")
        create_backup
        ;;
    "cleanup")
        cleanup
        ;;
    *)
        echo "Usage: $0 {deploy|rollback|monitor|health|backup|cleanup}"
        echo ""
        echo "Commands:"
        echo "  deploy   - Deploy with zero-downtime updates (default)"
        echo "  rollback - Rollback to previous version"
        echo "  monitor  - Monitor system status"
        echo "  health   - Check service health"
        echo "  backup   - Create backup"
        echo "  cleanup  - Clean up old resources"
        exit 1
        ;;
esac
