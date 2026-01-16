# Application Control Scripts

Simple scripts to manage the Regression Tracker Web Application.

## Available Scripts

### 🚀 start.sh
Start the application.

```bash
./start.sh
```

**What it does:**
- Checks if port 8000 is available
- Activates virtual environment (creates if needed)
- Verifies database exists
- Starts FastAPI server with hot-reload

**Output:**
```
Starting Regression Tracker Web Application...
Starting FastAPI server on http://localhost:8000
Press Ctrl+C to stop
```

---

### 🛑 stop.sh
Stop the running application.

```bash
./stop.sh
```

**What it does:**
- Finds process running on port 8000
- Kills the process gracefully
- Verifies port is released

**Output:**
```
Stopping Regression Tracker Web Application...
Application stopped successfully (PID: 12345)
Port 8000 is now free
```

---

### 🔄 restart.sh
Restart the application (stop + clear cache + start).

```bash
./restart.sh
```

**What it does:**
1. Stops the running application
2. Clears Python cache (`__pycache__`, `*.pyc`)
3. Starts the application fresh

**When to use:**
- After making code changes
- After pulling updates from git
- When experiencing issues
- After database migrations

**Output:**
```
========================================
  Regression Tracker - Restart
========================================

[1/3] Stopping application...
Application stopped successfully (PID: 12345)

[2/3] Clearing Python cache...
Cache cleared

[3/3] Starting application...
Starting FastAPI server on http://localhost:8000
```

---

## Quick Reference

| Task | Command |
|------|---------|
| Start application | `./start.sh` |
| Stop application | `./stop.sh` |
| Restart application | `./restart.sh` |
| Check if running | `lsof -i:8000` |
| View logs (if running) | Check terminal output |

---

## Troubleshooting

### Port already in use
If you see "Port 8000 is already in use":
```bash
./stop.sh
./start.sh
```

Or simply:
```bash
./restart.sh
```

### Application won't stop
Force kill all processes on port 8000:
```bash
lsof -ti:8000 | xargs kill -9
```

### Database not found
Run migrations first:
```bash
source venv/bin/activate
alembic upgrade head
```

### Virtual environment missing
The `start.sh` script will create it automatically, or manually:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## Production Deployment

For production, consider using a process manager like:

### Using systemd (Linux)
```bash
sudo systemctl restart regression-tracker
```

### Using PM2 (Node.js process manager)
```bash
pm2 restart regression-tracker
```

### Using Gunicorn (Production WSGI server)
```bash
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

---

## Development Workflow

**Typical workflow:**
1. Make code changes
2. Run `./restart.sh` to apply changes
3. Test at http://localhost:8000
4. Repeat

**After git pull:**
```bash
git pull origin develop
./restart.sh
```

**After database changes:**
```bash
alembic upgrade head
./restart.sh
```

---

## Notes

- All scripts use colored output for better visibility
- Scripts are safe to run multiple times
- Hot-reload is enabled in development (via `--reload` flag)
- Scripts automatically handle virtual environment activation
