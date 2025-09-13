# SSL Setup Guide for NCR Upload API

This guide explains how to set up SSL/HTTPS for the NCR Upload API using nginx as a reverse proxy.

## Overview

The deployment now includes:
- **Nginx** as a reverse proxy on port 80 (HTTP) and 443 (HTTPS)
- **Self-signed certificates** for development
- **Let's Encrypt certificates** for production
- **Automatic HTTP to HTTPS redirect** when SSL is enabled

## Quick Start

### 1. Deploy the Application
```bash
./deploy.sh deploy
```
This will start the application with nginx in development mode (HTTP only).

### 2. Enable SSL (Choose one option)

#### Option A: Self-signed Certificate (Development)
```bash
./deploy.sh setup-ssl
./deploy.sh enable-ssl
```

#### Option B: Let's Encrypt Certificate (Production)
```bash
# Set your domain and email
export DOMAIN_NAME="your-domain.com"
export SSL_EMAIL="your-email@example.com"

# Setup Let's Encrypt certificate
./deploy.sh setup-letsencrypt

# Enable SSL mode
./deploy.sh enable-ssl
```

## Configuration

### Environment Variables

- `DOMAIN_NAME`: Your domain name (default: `ncr-api.com`)
- `SSL_EMAIL`: Email for Let's Encrypt registration (default: `admin@ncr-api.com`)

### SSL Certificate Locations

- **Self-signed certificates**: `./ssl/live/$DOMAIN_NAME/`
- **Let's Encrypt certificates**: `./ssl/live/$DOMAIN_NAME/`

## Available Commands

| Command | Description |
|---------|-------------|
| `./deploy.sh deploy` | Deploy application (starts in HTTP mode) |
| `./deploy.sh setup-ssl` | Generate self-signed SSL certificate |
| `./deploy.sh setup-letsencrypt` | Setup Let's Encrypt certificate |
| `./deploy.sh enable-ssl` | Switch nginx to SSL mode |
| `./deploy.sh disable-ssl` | Switch nginx to development mode |
| `./deploy.sh renew-ssl` | Renew SSL certificates |

## File Upload with SSL

Once SSL is enabled, you can upload files using HTTPS:

```bash
# Upload with HTTPS
curl -X POST "https://your-domain.com/file-upload" \
  -F "job_id=your_job_id_here" \
  -F "delivery_file=@/path/to/your/delivery.zip"
```

## Monitoring

The monitoring endpoints are available at:
- `https://your-domain.com/health`
- `https://your-domain.com/celery-stats`
- `https://your-domain.com/memory-stats`
- `https://your-domain.com/redis-stats`

## Troubleshooting

### Certificate Issues
```bash
# Check certificate status
openssl x509 -in ./ssl/live/$DOMAIN_NAME/fullchain.pem -text -noout

# Test SSL connection
openssl s_client -connect your-domain.com:443 -servername your-domain.com
```

### Nginx Issues
```bash
# Check nginx logs
docker compose logs nginx

# Test nginx configuration
docker compose exec nginx nginx -t

# Reload nginx
docker compose exec nginx nginx -s reload
```

### Let's Encrypt Issues
```bash
# Check certificate renewal
docker compose run --rm certbot certificates

# Force renewal
docker compose run --rm certbot renew --force-renewal
```

## Security Features

The nginx configuration includes:
- **HTTP to HTTPS redirect**
- **Security headers** (HSTS, X-Frame-Options, etc.)
- **Rate limiting** (10 requests/second)
- **Large file upload support** (100MB)
- **Gzip compression**
- **SSL/TLS security** (TLS 1.2+)

## Production Checklist

Before going to production:
1. ✅ Set correct `DOMAIN_NAME` environment variable
2. ✅ Set correct `SSL_EMAIL` environment variable
3. ✅ Ensure DNS points to your server
4. ✅ Run `./deploy.sh setup-letsencrypt`
5. ✅ Run `./deploy.sh enable-ssl`
6. ✅ Test HTTPS endpoints
7. ✅ Set up certificate auto-renewal (cron job)

## Auto-renewal Setup

Add to crontab for automatic certificate renewal:
```bash
# Renew certificates every 2 months
0 3 1 */2 * cd /path/to/ncr_background_worker && ./deploy.sh renew-ssl
```
