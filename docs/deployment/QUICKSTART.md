# Quick Start Deployment Guide

Get the Regression Tracker Web Application running in production in under 10 minutes.

## Development Mode (Testing)

```bash
# Clone and setup
git clone https://github.com/yourusername/regression-tracker-web.git
cd regression-tracker-web
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your Jenkins credentials

# Initialize database
alembic upgrade head

# Run development server
./start.sh
```

Visit http://localhost:8000

## Production Mode (Single Server)

### Quick Production Start

```bash
# Clone and setup
git clone https://github.com/yourusername/regression-tracker-web.git
cd regression-tracker-web
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with production settings

# Initialize database
alembic upgrade head

# Run production server
./start_production.sh
```

### Install as System Service

```bash
# Run automated installation
sudo deployment/install.sh

# Configure environment
sudo nano /opt/regression-tracker-web/.env

# Run migrations
cd /opt/regression-tracker-web
source venv/bin/activate
alembic upgrade head

# Start service
sudo systemctl start regression-tracker
sudo systemctl enable regression-tracker

# Check status
sudo systemctl status regression-tracker
```

Visit http://your-server-ip:8000

## Docker Quick Start

```bash
# Clone repository
git clone https://github.com/yourusername/regression-tracker-web.git
cd regression-tracker-web

# Create environment file
cp .env.example .env
# Edit .env with your configuration

# Build and run
docker-compose up -d

# View logs
docker-compose logs -f web

# Initialize database (first time only)
docker-compose exec web alembic upgrade head
```

Visit http://localhost:8000

## Verification

Check that everything is working:

```bash
# Test basic health
curl http://localhost:8000/health

# Test detailed health
curl http://localhost:8000/health/detailed

# Test API
curl http://localhost:8000/api/v1

# View API documentation
# Open browser: http://localhost:8000/docs
```

## Next Steps

1. **Configure Jenkins Integration**
   - Add your Jenkins URL and credentials to `.env`
   - Test connection: Visit Admin page → Test Connection

2. **Import Historical Data**
   - Run the import script: `python scripts/import_existing_data.py`

3. **Enable Background Polling**
   - Set `AUTO_UPDATE_ENABLED=true` in `.env`
   - Configure `POLLING_INTERVAL_MINUTES` (default: 15)

4. **Set Up Monitoring**
   - Configure health check monitoring
   - Set up log aggregation
   - Enable metrics collection

5. **Security Hardening**
   - Generate and set `ADMIN_PIN_HASH`
   - Enable API key authentication
   - Configure HTTPS/SSL
   - Set up firewall rules

## Troubleshooting

### Port 8000 Already in Use

```bash
# Find and kill process
lsof -i :8000
kill -9 <PID>

# Or use different port
PORT=8080 ./start_production.sh
```

### Database Not Found

```bash
# Create database directory
mkdir -p data

# Run migrations
alembic upgrade head
```

### Permission Denied

```bash
# Fix permissions
chmod +x start.sh start_production.sh
chmod 755 scripts/*.py
```

### Dependencies Not Installing

```bash
# Update pip
pip install --upgrade pip

# Install build dependencies (Ubuntu/Debian)
sudo apt-get install python3-dev build-essential

# Install build dependencies (CentOS/RHEL)
sudo yum install python3-devel gcc
```

## Support

- Full documentation: [docs/deployment/PRODUCTION.md](PRODUCTION.md)
- API docs: http://localhost:8000/docs
- Issues: https://github.com/yourusername/regression-tracker-web/issues
