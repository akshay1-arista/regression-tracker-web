# Production Deployment Guide

This guide covers deploying the Regression Tracker Web Application to production environments.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Deployment Options](#deployment-options)
- [Linux Server Deployment](#linux-server-deployment)
- [Docker Deployment](#docker-deployment)
- [Kubernetes Deployment](#kubernetes-deployment)
- [Configuration](#configuration)
- [Monitoring](#monitoring)
- [Backup and Recovery](#backup-and-recovery)
- [Troubleshooting](#troubleshooting)

## Prerequisites

- Python 3.9 or higher
- Git
- Jenkins credentials (username + API token)
- Minimum 2GB RAM, 2 CPU cores recommended
- 10GB disk space for database and logs

## Deployment Options

### 1. Linux Server (Recommended for small to medium deployments)
- Uses systemd for process management
- Gunicorn for production WSGI server
- Suitable for single server deployments

### 2. Docker (Recommended for containerized environments)
- Portable and reproducible deployments
- Easy scaling with Docker Compose
- Suitable for cloud platforms

### 3. Kubernetes (Recommended for large scale deployments)
- High availability and auto-scaling
- Built-in health checks and rolling updates
- Suitable for enterprise environments

## Linux Server Deployment

### Automated Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/regression-tracker-web.git
cd regression-tracker-web

# Run installation script (requires sudo)
sudo deployment/install.sh
```

The installation script will:
1. Create installation directory at `/opt/regression-tracker-web`
2. Set up Python virtual environment
3. Install dependencies
4. Configure systemd service
5. Set up data directories with proper permissions

### Manual Installation

If you prefer manual installation:

```bash
# 1. Create installation directory
sudo mkdir -p /opt/regression-tracker-web
cd /opt/regression-tracker-web

# 2. Clone repository
git clone https://github.com/yourusername/regression-tracker-web.git .

# 3. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 4. Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 5. Configure environment
cp .env.example .env
# Edit .env with your configuration
nano .env

# 6. Run database migrations
alembic upgrade head

# 7. Install systemd service
sudo cp deployment/regression-tracker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable regression-tracker
sudo systemctl start regression-tracker
```

### Service Management

```bash
# Start the service
sudo systemctl start regression-tracker

# Stop the service
sudo systemctl stop regression-tracker

# Restart the service
sudo systemctl restart regression-tracker

# Check service status
sudo systemctl status regression-tracker

# View logs
sudo journalctl -u regression-tracker -f

# Enable auto-start on boot
sudo systemctl enable regression-tracker
```

## Docker Deployment

### Using Docker Compose (Recommended)

Create a `docker-compose.yml` file:

```yaml
version: '3.8'

services:
  web:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=sqlite:///./data/regression_tracker.db
      - JENKINS_URL=${JENKINS_URL}
      - JENKINS_USER=${JENKINS_USER}
      - JENKINS_API_TOKEN=${JENKINS_API_TOKEN}
      - AUTO_UPDATE_ENABLED=true
      - POLLING_INTERVAL_MINUTES=15
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

  # Optional: Use PostgreSQL instead of SQLite for production
  # db:
  #   image: postgres:14
  #   environment:
  #     - POSTGRES_DB=regression_tracker
  #     - POSTGRES_USER=tracker
  #     - POSTGRES_PASSWORD=secure_password
  #   volumes:
  #     - postgres_data:/var/lib/postgresql/data
  #   restart: unless-stopped

# volumes:
#   postgres_data:
```

Create a `Dockerfile`:

```dockerfile
FROM python:3.9-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create data directories
RUN mkdir -p data logs

# Expose port
EXPOSE 8000

# Run with gunicorn
CMD ["gunicorn", "app.main:app", "-c", "gunicorn.conf.py"]
```

Deploy:

```bash
# Start services
docker-compose up -d

# View logs
docker-compose logs -f web

# Stop services
docker-compose down

# Rebuild and restart
docker-compose up -d --build
```

## Kubernetes Deployment

### Deployment Manifest

Create `k8s-deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: regression-tracker
  labels:
    app: regression-tracker
spec:
  replicas: 3
  selector:
    matchLabels:
      app: regression-tracker
  template:
    metadata:
      labels:
        app: regression-tracker
    spec:
      containers:
      - name: regression-tracker
        image: your-registry/regression-tracker:latest
        ports:
        - containerPort: 8000
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: regression-tracker-secrets
              key: database-url
        - name: JENKINS_API_TOKEN
          valueFrom:
            secretKeyRef:
              name: regression-tracker-secrets
              key: jenkins-token
        livenessProbe:
          httpGet:
            path: /health/live
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health/ready
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 5
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "2000m"
        volumeMounts:
        - name: data
          mountPath: /app/data
        - name: logs
          mountPath: /app/logs
      volumes:
      - name: data
        persistentVolumeClaim:
          claimName: regression-tracker-data
      - name: logs
        persistentVolumeClaim:
          claimName: regression-tracker-logs
---
apiVersion: v1
kind: Service
metadata:
  name: regression-tracker
spec:
  selector:
    app: regression-tracker
  ports:
  - protocol: TCP
    port: 80
    targetPort: 8000
  type: LoadBalancer
```

Deploy to Kubernetes:

```bash
# Create secrets
kubectl create secret generic regression-tracker-secrets \
  --from-literal=database-url="postgresql://..." \
  --from-literal=jenkins-token="your-token"

# Apply deployment
kubectl apply -f k8s-deployment.yaml

# Check status
kubectl get pods -l app=regression-tracker
kubectl logs -f deployment/regression-tracker

# Scale deployment
kubectl scale deployment regression-tracker --replicas=5
```

## Configuration

### Environment Variables

Key configuration options (see `.env.example` for full list):

```bash
# Database
DATABASE_URL=sqlite:///./data/regression_tracker.db

# Jenkins
JENKINS_URL=https://jenkins.example.com
JENKINS_USER=username
JENKINS_API_TOKEN=your_api_token_here

# Polling
AUTO_UPDATE_ENABLED=true
POLLING_INTERVAL_MINUTES=15

# Application
DEBUG=false
HOST=0.0.0.0
PORT=8000

# Security
ADMIN_PIN_HASH=sha256_hash_of_pin

# Performance
GUNICORN_WORKERS=9  # (2 * CPU cores) + 1
RATE_LIMIT_PER_MINUTE=100
CACHE_ENABLED=true
```

### Security Configuration

#### Generate Admin PIN Hash

```bash
# Generate SHA-256 hash of your PIN
echo -n "your_pin_here" | sha256sum
```

Add to `.env`:
```bash
ADMIN_PIN_HASH=03ac674216f3e15c761ee1a5e255f067953623c8b388b4459e13f978d7c846f4
```

#### Enable API Key Authentication

```bash
# Generate random API keys
API_KEY=$(openssl rand -hex 32)
ADMIN_API_KEY=$(openssl rand -hex 32)

# Add to .env
echo "API_KEY=$API_KEY" >> .env
echo "ADMIN_API_KEY=$ADMIN_API_KEY" >> .env
```

## Monitoring

### Health Check Endpoints

The application provides multiple health check endpoints:

- **Basic**: `GET /health` - Simple health check
- **Detailed**: `GET /health/detailed` - Comprehensive status (database, scheduler, cache)
- **Liveness**: `GET /health/live` - Kubernetes liveness probe
- **Readiness**: `GET /health/ready` - Kubernetes readiness probe

### Monitoring with Prometheus

Add to `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'regression-tracker'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'
    scrape_interval: 15s
```

### Log Monitoring

Logs are written to:
- **Application logs**: `logs/application.log`
- **Systemd journal**: `journalctl -u regression-tracker`
- **Docker logs**: `docker-compose logs -f web`

## Backup and Recovery

### Database Backup

```bash
# SQLite backup
cp data/regression_tracker.db data/regression_tracker.db.backup.$(date +%Y%m%d)

# PostgreSQL backup
pg_dump -U tracker regression_tracker > backup_$(date +%Y%m%d).sql
```

### Automated Backups

Add to crontab:

```bash
# Daily backup at 2 AM
0 2 * * * /opt/regression-tracker-web/scripts/backup_database.sh
```

Create `scripts/backup_database.sh`:

```bash
#!/bin/bash
BACKUP_DIR="/opt/regression-tracker-web/backups"
mkdir -p "$BACKUP_DIR"

DATE=$(date +%Y%m%d_%H%M%S)
cp /opt/regression-tracker-web/data/regression_tracker.db \
   "$BACKUP_DIR/regression_tracker_$DATE.db"

# Keep only last 30 days of backups
find "$BACKUP_DIR" -name "*.db" -mtime +30 -delete
```

### Restore from Backup

```bash
# Stop the application
sudo systemctl stop regression-tracker

# Restore database
cp backups/regression_tracker_20250117.db data/regression_tracker.db

# Start the application
sudo systemctl start regression-tracker
```

## Troubleshooting

### Common Issues

#### Port Already in Use

```bash
# Find process using port 8000
lsof -i :8000

# Kill the process
kill -9 <PID>
```

#### Database Migration Failed

```bash
# Check current migration version
alembic current

# Reset to latest
alembic downgrade base
alembic upgrade head
```

#### High Memory Usage

- Reduce `GUNICORN_WORKERS` in environment
- Enable `max_requests=1000` in gunicorn config
- Add memory limits in systemd service:

```ini
[Service]
MemoryLimit=2G
```

#### Slow Response Times

- Enable Redis cache: Set `REDIS_URL` in `.env`
- Increase database connection pool
- Add database indexes for frequently queried fields

### Performance Tuning

#### Optimize Worker Count

```bash
# Calculate optimal workers
python3 -c "import multiprocessing; print((multiprocessing.cpu_count() * 2) + 1)"
```

#### Enable Response Compression

Add to gunicorn config:
```python
# In gunicorn.conf.py
raw_env = [
    'PYTHONUNBUFFERED=1',
]
```

#### Database Optimization

```sql
-- Add indexes for common queries
CREATE INDEX idx_builds_job_id ON builds(job_id);
CREATE INDEX idx_test_results_build_id ON test_results(build_id);
CREATE INDEX idx_jobs_module_id ON jobs(module_id);
```

## Performance Testing

Run the performance test suite:

```bash
# Run all performance tests
./scripts/run_performance_tests.sh

# Run specific test
pytest tests/test_performance.py::test_throughput -v
```

## Data Validation

Validate data integrity:

```bash
# Run validation script
python scripts/validate_data.py --verbose

# Export validation report
python scripts/validate_data.py --export-report reports/validation.json
```

## Updating the Application

### Rolling Update (Zero Downtime)

```bash
# Pull latest code
cd /opt/regression-tracker-web
git pull origin main

# Install new dependencies
source venv/bin/activate
pip install -r requirements.txt

# Run migrations
alembic upgrade head

# Reload application (graceful restart)
sudo systemctl reload regression-tracker
```

### Blue-Green Deployment

```bash
# Deploy new version to secondary port
GUNICORN_WORKERS=9 PORT=8001 gunicorn app.main:app -c gunicorn.conf.py &

# Test new version
curl http://localhost:8001/health/detailed

# Switch load balancer to new version
# ... update nginx/load balancer config ...

# Stop old version
sudo systemctl stop regression-tracker
```

## Support

For issues or questions:
- GitHub Issues: https://github.com/yourusername/regression-tracker-web/issues
- Documentation: `/docs` folder
- API Documentation: http://localhost:8000/docs (when running)
