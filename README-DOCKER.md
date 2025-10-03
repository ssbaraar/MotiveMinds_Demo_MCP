# Docker Deployment Guide for MotiveMinds MCP Server

This guide explains how to deploy the MotiveMinds MCP Server using Docker and Docker Compose.

## Prerequisites

- Docker Engine 20.10+
- Docker Compose 2.0+
- `.env` file with required SAP credentials

## Quick Start

### 1. Setup Environment Variables

Copy the example environment file and configure it:

```bash
cp .env.example .env
```

Edit `.env` with your SAP credentials:

```env
# SAP Configuration
SAP_HOST=https://your-sap-host.com
SAP_PORT=443
SAP_CLIENT=100

# Authentication
AUTH_USERNAME=your_username
AUTH_PASSWORD=your_password

# SAP BPA Configuration (if using workflow features)
SAP_BPA_BASE_URL=https://your-bpa-instance.com
SAP_BPA_TOKEN_URL=https://your-auth-server.com/oauth/token
SAP_BPA_CLIENT_ID=your_client_id
SAP_BPA_CLIENT_SECRET=your_client_secret

# Environment
ENVIRONMENT=production
PORT=10000
```

### 2. Build and Run

**Development mode:**
```bash
docker-compose up --build
```

**Production mode with Nginx:**
```bash
docker-compose --profile production up --build -d
```

**Background mode:**
```bash
docker-compose up -d
```

### 3. Verify Deployment

Check if the service is running:
```bash
docker-compose ps
```

View logs:
```bash
docker-compose logs -f motiveminds-mcp
```

Test the health endpoint:
```bash
curl http://localhost:10000/health
```

## Docker Compose Services

### Main Service: `motiveminds-mcp`

The primary MCP server service with:
- **Port**: 10000 (configurable via PORT env var)
- **Health checks**: Automatic monitoring
- **Resource limits**: 2 CPU cores, 1GB RAM max
- **Auto-restart**: Unless manually stopped
- **Logging**: JSON format, 10MB max per file, 3 files rotation

### Optional Service: `nginx`

Reverse proxy for production (activated with `--profile production`):
- **Ports**: 80 (HTTP), 443 (HTTPS)
- **Features**: Rate limiting, SSL/TLS support, load balancing ready
- **Configuration**: `nginx.conf`

## Management Commands

### Start Services
```bash
docker-compose up -d
```

### Stop Services
```bash
docker-compose down
```

### Restart Services
```bash
docker-compose restart
```

### View Logs
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f motiveminds-mcp
```

### Rebuild After Code Changes
```bash
docker-compose up --build -d
```

### Scale Services (if needed)
```bash
docker-compose up -d --scale motiveminds-mcp=3
```

## Resource Management

### Current Limits
- **CPU**: 2 cores max, 0.5 cores reserved
- **Memory**: 1GB max, 256MB reserved

### Adjust Resources

Edit `docker-compose.yml`:
```yaml
deploy:
  resources:
    limits:
      cpus: '4.0'      # Increase CPU limit
      memory: 2G       # Increase memory limit
    reservations:
      cpus: '1.0'
      memory: 512M
```

## Production Deployment

### 1. Enable Nginx Reverse Proxy

```bash
docker-compose --profile production up -d
```

### 2. Configure SSL/TLS

Create SSL directory and add certificates:
```bash
mkdir -p ssl
# Add your cert.pem and key.pem files
```

Uncomment HTTPS section in `nginx.conf` and update domain name.

### 3. Environment Configuration

Set production environment:
```env
ENVIRONMENT=production
```

This enables:
- SSL certificate verification
- Production logging levels
- Security hardening

### 4. Monitoring

Check service health:
```bash
docker-compose ps
docker-compose logs --tail=100 motiveminds-mcp
```

Monitor resource usage:
```bash
docker stats motiveminds-mcp-server
```

## Troubleshooting

### Service Won't Start

1. Check logs:
```bash
docker-compose logs motiveminds-mcp
```

2. Verify environment variables:
```bash
docker-compose config
```

3. Check port availability:
```bash
netstat -an | grep 10000
```

### Connection Issues

1. Verify network:
```bash
docker network ls
docker network inspect motiveminds_demo_mcp_mcp-network
```

2. Test from inside container:
```bash
docker-compose exec motiveminds-mcp curl http://localhost:10000/health
```

### Performance Issues

1. Check resource usage:
```bash
docker stats
```

2. Increase resource limits in `docker-compose.yml`

3. Review logs for bottlenecks:
```bash
docker-compose logs --tail=1000 motiveminds-mcp | grep -i error
```

### SSL/Certificate Issues

If using development mode with self-signed certificates:
```env
ENVIRONMENT=development
```

For production, ensure valid SSL certificates are configured.

## Backup and Maintenance

### Backup Logs
```bash
docker cp motiveminds-mcp-server:/app/logs ./backup-logs-$(date +%Y%m%d)
```

### Update Image
```bash
docker-compose pull
docker-compose up -d
```

### Clean Up
```bash
# Remove stopped containers
docker-compose down

# Remove volumes (caution: deletes data)
docker-compose down -v

# Remove images
docker-compose down --rmi all
```

## Network Configuration

The compose file creates a custom bridge network:
- **Name**: `mcp-network`
- **Subnet**: 172.28.0.0/16
- **Driver**: bridge

Services can communicate using service names as hostnames.

## Security Best Practices

1. **Never commit `.env` file** - Keep credentials secure
2. **Use secrets management** - Consider Docker secrets for production
3. **Enable SSL/TLS** - Use HTTPS in production
4. **Regular updates** - Keep base images updated
5. **Resource limits** - Prevent resource exhaustion
6. **Network isolation** - Use custom networks
7. **Read-only volumes** - Mount sensitive files as read-only

## Advanced Configuration

### Using Docker Secrets (Swarm Mode)

```yaml
secrets:
  sap_password:
    external: true

services:
  motiveminds-mcp:
    secrets:
      - sap_password
    environment:
      - AUTH_PASSWORD_FILE=/run/secrets/sap_password
```

### Custom Health Check

Modify in `docker-compose.yml`:
```yaml
healthcheck:
  test: ["CMD", "python", "-c", "import requests; requests.get('http://localhost:10000/health')"]
  interval: 30s
  timeout: 10s
  retries: 3
```

## Support

For issues or questions:
1. Check logs: `docker-compose logs -f`
2. Review environment configuration
3. Verify SAP connectivity
4. Check Docker and Docker Compose versions

## License

[Your License Here]