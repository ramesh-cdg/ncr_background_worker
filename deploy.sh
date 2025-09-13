#!/bin/bash

# Production deployment script with zero-downtime updates
set -e

# Configuration
COMPOSE_FILE="docker-compose.yml"
BACKUP_DIR="./backups"
LOG_FILE="./deploy.log"
SSL_DIR="./ssl"
CERTBOT_DIR="./certbot"
DOMAIN_NAME="${DOMAIN_NAME:-ncr-api.com}"
EMAIL="${SSL_EMAIL:-admin@ncr-api.com}"

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

# Setup SSL certificates
setup_ssl() {
    log "Setting up SSL certificates..."
    
    # Create directories
    mkdir -p $SSL_DIR
    mkdir -p $CERTBOT_DIR/www
    
    # Check if certificates already exist
    if [ -f "$SSL_DIR/live/$DOMAIN_NAME/fullchain.pem" ] && [ -f "$SSL_DIR/live/$DOMAIN_NAME/privkey.pem" ]; then
        log "SSL certificates already exist for $DOMAIN_NAME"
        return 0
    fi
    
    log "Generating self-signed certificate for development..."
    
    # Create self-signed certificate for development
    mkdir -p $SSL_DIR/live/$DOMAIN_NAME
    
    # Generate private key
    openssl genrsa -out $SSL_DIR/live/$DOMAIN_NAME/privkey.pem 2048
    
    # Generate certificate signing request
    openssl req -new -key $SSL_DIR/live/$DOMAIN_NAME/privkey.pem -out $SSL_DIR/live/$DOMAIN_NAME/cert.csr -subj "/C=US/ST=State/L=City/O=Organization/CN=$DOMAIN_NAME"
    
    # Generate self-signed certificate
    openssl x509 -req -days 365 -in $SSL_DIR/live/$DOMAIN_NAME/cert.csr -signkey $SSL_DIR/live/$DOMAIN_NAME/privkey.pem -out $SSL_DIR/live/$DOMAIN_NAME/fullchain.pem
    
    # Clean up CSR file
    rm $SSL_DIR/live/$DOMAIN_NAME/cert.csr
    
    log "Self-signed SSL certificate generated for $DOMAIN_NAME"
    warning "For production, replace with Let's Encrypt certificates using: ./deploy.sh setup-letsencrypt"
}

# Setup Let's Encrypt certificates (using OpenSSL for now)
setup_letsencrypt() {
    log "Setting up SSL certificates for $DOMAIN_NAME using OpenSSL..."
    
    # Create directories
    mkdir -p $SSL_DIR
    mkdir -p $SSL_DIR/live/$DOMAIN_NAME
    
    # Check if certificates already exist
    if [ -f "$SSL_DIR/live/$DOMAIN_NAME/fullchain.pem" ] && [ -f "$SSL_DIR/live/$DOMAIN_NAME/privkey.pem" ]; then
        log "SSL certificates already exist for $DOMAIN_NAME"
        return 0
    fi
    
    log "Generating SSL certificate for $DOMAIN_NAME using OpenSSL..."
    
    # Create a more comprehensive certificate with Subject Alternative Names
    cat > /tmp/cert.conf << EOF
[req]
default_bits = 2048
prompt = no
default_md = sha256
distinguished_name = dn
req_extensions = v3_req

[dn]
C=US
ST=State
L=City
O=Organization
CN=$DOMAIN_NAME

[v3_req]
basicConstraints = CA:FALSE
keyUsage = nonRepudiation, digitalSignature, keyEncipherment
subjectAltName = @alt_names

[alt_names]
DNS.1 = $DOMAIN_NAME
DNS.2 = www.$DOMAIN_NAME
EOF
    
    # Generate private key
    openssl genrsa -out $SSL_DIR/live/$DOMAIN_NAME/privkey.pem 2048
    
    # Generate certificate signing request
    openssl req -new -key $SSL_DIR/live/$DOMAIN_NAME/privkey.pem -out $SSL_DIR/live/$DOMAIN_NAME/cert.csr -config /tmp/cert.conf
    
    # Generate self-signed certificate with SAN
    openssl x509 -req -days 365 -in $SSL_DIR/live/$DOMAIN_NAME/cert.csr -signkey $SSL_DIR/live/$DOMAIN_NAME/privkey.pem -out $SSL_DIR/live/$DOMAIN_NAME/fullchain.pem -extensions v3_req -extfile /tmp/cert.conf
    
    # Clean up temporary files
    rm $SSL_DIR/live/$DOMAIN_NAME/cert.csr
    rm /tmp/cert.conf
    
    log "SSL certificate generated successfully for $DOMAIN_NAME"
    log "Certificate includes Subject Alternative Names for $DOMAIN_NAME and www.$DOMAIN_NAME"
}

# Renew SSL certificates
renew_ssl() {
    log "Renewing SSL certificates..."
    
    # For OpenSSL certificates, we need to regenerate them
    log "Regenerating SSL certificate for $DOMAIN_NAME..."
    setup_letsencrypt
    
    # Reload nginx
    docker compose exec nginx nginx -s reload
    
    log "SSL certificate renewal completed"
}

# Switch nginx to SSL mode
enable_ssl() {
    log "Switching nginx to SSL mode..."
    
    # Check if SSL certificates exist
    if [ ! -f "$SSL_DIR/live/$DOMAIN_NAME/fullchain.pem" ] || [ ! -f "$SSL_DIR/live/$DOMAIN_NAME/privkey.pem" ]; then
        error "SSL certificates not found. Run 'setup-ssl' or 'setup-letsencrypt' first."
    fi
    
    # Switch nginx configuration to SSL mode
    cp nginx.conf nginx-ssl.conf
    sed -i "s|./nginx-dev.conf:/etc/nginx/nginx.conf:ro|./nginx-ssl.conf:/etc/nginx/nginx.conf:ro|g" docker-compose.yml
    
    # Restart nginx with SSL configuration
    docker compose up -d nginx
    
    log "Nginx switched to SSL mode successfully!"
    log "API is now available at: https://$DOMAIN_NAME"
}

# Switch nginx to development mode
disable_ssl() {
    log "Switching nginx to development mode..."
    
    # Switch nginx configuration to development mode
    sed -i "s|./nginx-ssl.conf:/etc/nginx/nginx.conf:ro|./nginx-dev.conf:/etc/nginx/nginx.conf:ro|g" docker-compose.yml
    
    # Restart nginx with development configuration
    docker compose up -d nginx
    
    log "Nginx switched to development mode successfully!"
    log "API is now available at: http://$DOMAIN_NAME"
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
    health_check "nginx"
    
    # Final health check
    log "Performing final health check..."
    health_check "web"
    health_check "worker"
    health_check "beat"
    health_check "flower"
    health_check "nginx"
    
    log "Deployment completed successfully!"
    log "API is now available at:"
    log "  HTTP:  http://localhost"
    log ""
    log "To enable SSL:"
    log "  1. Run: ./deploy.sh setup-ssl (for self-signed) or ./deploy.sh setup-letsencrypt (for Let's Encrypt)"
    log "  2. Run: ./deploy.sh enable-ssl"
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
        curl -s http://localhost/celery-stats | jq '.' 2>/dev/null || echo "Celery stats unavailable"
        
        echo -e "\n=== Memory Stats ==="
        curl -s http://localhost/memory-stats | jq '.' 2>/dev/null || echo "Memory stats unavailable"
        
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
        health_check "nginx"
        ;;
    "backup")
        create_backup
        ;;
    "cleanup")
        cleanup
        ;;
    "setup-ssl")
        check_dependencies
        setup_ssl
        ;;
    "setup-letsencrypt")
        check_dependencies
        setup_letsencrypt
        ;;
    "renew-ssl")
        renew_ssl
        ;;
    "enable-ssl")
        enable_ssl
        ;;
    "disable-ssl")
        disable_ssl
        ;;
    *)
        echo "Usage: $0 {deploy|rollback|monitor|health|backup|cleanup|setup-ssl|setup-letsencrypt|renew-ssl|enable-ssl|disable-ssl}"
        echo ""
        echo "Commands:"
        echo "  deploy           - Deploy with zero-downtime updates (default)"
        echo "  rollback         - Rollback to previous version"
        echo "  monitor          - Monitor system status"
        echo "  health           - Check service health"
        echo "  backup           - Create backup"
        echo "  cleanup          - Clean up old resources"
        echo "  setup-ssl        - Setup self-signed SSL certificates"
        echo "  setup-letsencrypt - Setup SSL certificates using OpenSSL"
        echo "  renew-ssl        - Renew SSL certificates"
        echo "  enable-ssl       - Switch nginx to SSL mode"
        echo "  disable-ssl      - Switch nginx to development mode"
        echo ""
        echo "Environment variables:"
        echo "  DOMAIN_NAME      - Domain name for SSL (default: ncr-api.com)"
        echo "  SSL_EMAIL        - Email for Let's Encrypt (default: admin@ncr-api.com)"
        exit 1
        ;;
esac
