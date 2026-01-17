"""
Gunicorn configuration for production deployment.

This file configures Gunicorn for running the Regression Tracker Web Application
in production environments with optimal performance and reliability.
"""
import multiprocessing
import os

# Server Socket
bind = f"{os.getenv('HOST', '0.0.0.0')}:{os.getenv('PORT', '8000')}"
backlog = 2048

# Worker Processes
workers = int(os.getenv('GUNICORN_WORKERS', multiprocessing.cpu_count() * 2 + 1))
worker_class = 'uvicorn.workers.UvicornWorker'
worker_connections = 1000
max_requests = int(os.getenv('GUNICORN_MAX_REQUESTS', '1000'))  # Restart workers after this many requests (prevents memory leaks)
max_requests_jitter = int(os.getenv('GUNICORN_MAX_REQUESTS_JITTER', '50'))  # Randomize restart to avoid all workers restarting at once
timeout = int(os.getenv('GUNICORN_TIMEOUT', '120'))  # Workers silent for more than this are killed (SSE streams send heartbeats)
graceful_timeout = 30  # Timeout for graceful workers restart
keepalive = 5  # Keep-alive timeout

# Process Naming
proc_name = 'regression-tracker-web'

# Logging
accesslog = os.getenv('GUNICORN_ACCESS_LOG', '-')  # '-' means stdout
errorlog = os.getenv('GUNICORN_ERROR_LOG', '-')   # '-' means stderr
loglevel = os.getenv('GUNICORN_LOG_LEVEL', 'info')
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Server Mechanics
daemon = False  # Don't daemonize (we'll use systemd for that)
pidfile = None  # No PID file (systemd handles this)
umask = 0
user = None  # Run as current user
group = None  # Run as current group
tmp_upload_dir = None

# SSL (optional - uncomment and configure if needed)
# keyfile = '/path/to/keyfile'
# certfile = '/path/to/certfile'
# ca_certs = '/path/to/ca_certs'
# cert_reqs = 2  # ssl.CERT_REQUIRED
# ssl_version = 2  # ssl.PROTOCOL_TLSv1_2
# ciphers = 'TLS_AES_256_GCM_SHA384'

# Security
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190

# Development/Debug Settings
reload = os.getenv('GUNICORN_RELOAD', 'false').lower() == 'true'
reload_engine = 'auto'

# Preload application code before worker processes are forked
# This saves RAM and time but requires restart for code changes
preload_app = True


def on_starting(server):
    """Called just before the master process is initialized."""
    server.log.info("Starting Regression Tracker Web Application")


def on_reload(server):
    """Called to recycle workers during a reload via SIGHUP."""
    server.log.info("Reloading workers")


def when_ready(server):
    """Called just after the server is started."""
    server.log.info("Server is ready. Spawning workers")


def pre_fork(server, worker):
    """Called just before a worker is forked."""
    pass


def post_fork(server, worker):
    """Called just after a worker has been forked."""
    server.log.info(f"Worker spawned (pid: {worker.pid})")


def pre_exec(server):
    """Called just before a new master process is forked."""
    server.log.info("Forked child, re-executing")


def worker_int(worker):
    """Called just after a worker exited on SIGINT or SIGQUIT."""
    worker.log.info(f"Worker received INT or QUIT signal (pid: {worker.pid})")


def worker_abort(worker):
    """Called when a worker received the SIGABRT signal."""
    worker.log.info(f"Worker received SIGABRT signal (pid: {worker.pid})")
