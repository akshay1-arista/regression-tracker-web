# Security Setup Guide

This guide covers the security configuration for the Regression Tracker application, including admin PIN authentication and secure credential management.

## Table of Contents

- [Overview](#overview)
- [Admin PIN Authentication](#admin-pin-authentication)
  - [Initial Setup](#initial-setup)
  - [Generating a PIN Hash](#generating-a-pin-hash)
  - [Setting Environment Variable](#setting-environment-variable)
- [Jenkins Credentials](#jenkins-credentials)
- [Security Best Practices](#security-best-practices)
- [PIN Rotation](#pin-rotation)
- [Troubleshooting](#troubleshooting)

## Overview

The Regression Tracker implements two key security features:

1. **PIN-Based Admin Authentication**: All admin endpoints require a PIN via the `X-Admin-PIN` HTTP header
2. **Environment-Based Credential Management**: Jenkins credentials are stored only in environment variables, never in the database

## Admin PIN Authentication

### Initial Setup

All admin endpoints (`/api/v1/admin/*`) are protected by PIN authentication. The frontend automatically prompts for a PIN when accessing the admin page.

### Generating a PIN Hash

The application uses SHA-256 hashing for PIN security. To generate a PIN hash:

**Option 1: Using Python (Recommended)**

```bash
cd /path/to/regression-tracker-web
python3 -c "from app.utils.security import hash_pin; print(hash_pin('YOUR_PIN_HERE'))"
```

Replace `YOUR_PIN_HERE` with your desired PIN (e.g., `1234`).

**Option 2: Using the Python REPL**

```python
import hashlib
pin = "YOUR_PIN_HERE"
pin_hash = hashlib.sha256(pin.encode()).hexdigest()
print(pin_hash)
```

**Example Output:**
```
03ac674216f3e15c761ee1a5e255f067953623c8b388b4459e13f978d7c846f4
```

### Setting Environment Variable

Once you have your PIN hash, set it as an environment variable:

**For Development (Linux/Mac):**

```bash
export ADMIN_PIN_HASH="03ac674216f3e15c761ee1a5e255f067953623c8b388b4459e13f978d7c846f4"
```

**For Production (systemd service):**

Edit your systemd service file (e.g., `/etc/systemd/system/regression-tracker.service`):

```ini
[Service]
Environment="ADMIN_PIN_HASH=03ac674216f3e15c761ee1a5e255f067953623c8b388b4459e13f978d7c846f4"
```

Then reload and restart the service:

```bash
sudo systemctl daemon-reload
sudo systemctl restart regression-tracker
```

**For Production (Docker):**

In your `docker-compose.yml`:

```yaml
services:
  app:
    environment:
      - ADMIN_PIN_HASH=03ac674216f3e15c761ee1a5e255f067953623c8b388b4459e13f978d7c846f4
```

Or using Docker run:

```bash
docker run -e ADMIN_PIN_HASH=03ac... regression-tracker
```

**For Production (.env file):**

Create or edit `.env` file:

```env
ADMIN_PIN_HASH=03ac674216f3e15c761ee1a5e255f067953623c8b388b4459e13f978d7c846f4
```

⚠️ **IMPORTANT**: Never commit the `.env` file to version control. Add it to `.gitignore`.

## Jenkins Credentials

Jenkins credentials are stored exclusively in environment variables for security. The database does NOT store credentials.

### Required Environment Variables

Set these environment variables before starting the application:

```bash
export JENKINS_URL="https://jenkins.example.com"
export JENKINS_USER="your_jenkins_username"
export JENKINS_API_TOKEN="your_jenkins_api_token"
```

### Obtaining Jenkins API Token

1. Log in to Jenkins
2. Click your name in the top-right corner
3. Click "Configure"
4. Under "API Token", click "Add new Token"
5. Give it a name (e.g., "Regression Tracker")
6. Click "Generate"
7. Copy the generated token immediately (you won't see it again)

### Setting in Production

**systemd service:**

```ini
[Service]
Environment="JENKINS_URL=https://jenkins.example.com"
Environment="JENKINS_USER=admin"
Environment="JENKINS_API_TOKEN=your_token_here"
```

**Docker Compose:**

```yaml
services:
  app:
    environment:
      - JENKINS_URL=https://jenkins.example.com
      - JENKINS_USER=admin
      - JENKINS_API_TOKEN=your_token_here
```

**⚠️ CRITICAL**: Remove any existing Jenkins credentials from the database!

## Security Best Practices

### 1. PIN Selection

- **DO**: Use a strong, random PIN (6-8 digits minimum)
- **DO**: Change the default PIN immediately
- **DON'T**: Use sequential numbers (e.g., 1234, 9876)
- **DON'T**: Use common PINs (e.g., 0000, 1111)

### 2. Credential Storage

- **DO**: Store credentials only in environment variables
- **DO**: Use secret management tools (e.g., HashiCorp Vault, AWS Secrets Manager)
- **DO**: Rotate credentials regularly
- **DON'T**: Store credentials in the database
- **DON'T**: Commit credentials to version control
- **DON'T**: Share credentials via insecure channels

### 3. Access Control

- **DO**: Limit admin PIN knowledge to authorized personnel only
- **DO**: Use unique PINs for different environments (dev/staging/prod)
- **DO**: Monitor admin endpoint access logs
- **DON'T**: Share PINs via email, Slack, or other insecure channels

### 4. Network Security

- **DO**: Use HTTPS in production
- **DO**: Implement network-level access controls
- **DO**: Use VPN for remote access
- **DON'T**: Expose the admin interface to the public internet

## PIN Rotation

Rotating the admin PIN periodically enhances security. Follow these steps:

### Step 1: Generate New PIN Hash

```bash
python3 -c "from app.utils.security import hash_pin; print(hash_pin('NEW_PIN_HERE'))"
```

### Step 2: Update Environment Variable

**Development:**

```bash
export ADMIN_PIN_HASH="new_hash_here"
```

**Production (systemd):**

1. Edit service file: `sudo systemctl edit regression-tracker --full`
2. Update `ADMIN_PIN_HASH` value
3. Reload: `sudo systemctl daemon-reload`
4. Restart: `sudo systemctl restart regression-tracker`

**Production (Docker):**

1. Update `docker-compose.yml` or `.env` file
2. Restart container: `docker-compose restart app`

### Step 3: Verify

1. Access admin page
2. Enter new PIN
3. Confirm successful authentication

### Step 4: Notify Team

Inform authorized personnel of the PIN change through secure channels.

## Troubleshooting

### Issue: "Admin PIN required" Error

**Cause**: No PIN provided or ADMIN_PIN_HASH not configured

**Solution**:
1. Verify `ADMIN_PIN_HASH` environment variable is set
2. Restart the application after setting the variable
3. Check logs for configuration errors

```bash
# Verify environment variable is set
echo $ADMIN_PIN_HASH

# Check application logs
tail -f /var/log/regression-tracker/application.log
```

### Issue: "Invalid admin PIN" Error

**Cause**: Incorrect PIN or hash mismatch

**Solution**:
1. Verify you're using the correct PIN
2. Regenerate the hash and ensure it matches the environment variable
3. Check for whitespace or encoding issues in the hash

```bash
# Test PIN hash generation
python3 -c "from app.utils.security import hash_pin, verify_pin; h = hash_pin('1234'); print(f'Hash: {h}'); print(f'Verify: {verify_pin(\"1234\", h)}')"
```

### Issue: "Jenkins credentials not configured" Error

**Cause**: Missing Jenkins environment variables

**Solution**:
1. Set all three required variables:
   ```bash
   export JENKINS_URL="https://jenkins.example.com"
   export JENKINS_USER="username"
   export JENKINS_API_TOKEN="token"
   ```
2. Restart the application
3. Verify variables are accessible:
   ```bash
   python3 -c "from app.config import get_settings; s = get_settings(); print(f'URL: {s.JENKINS_URL}'); print(f'User: {s.JENKINS_USER}'); print(f'Token: {\"SET\" if s.JENKINS_API_TOKEN else \"NOT SET\"}')"
   ```

### Issue: Frontend Shows Repeated PIN Prompts

**Cause**: PIN not being accepted by backend

**Solution**:
1. Open browser developer console (F12)
2. Check for 401/403 errors in Network tab
3. Verify the `X-Admin-PIN` header is being sent
4. Check that ADMIN_PIN_HASH environment variable matches the hash of your PIN
5. Clear browser cache and cookies
6. Try in incognito/private browsing mode

### Issue: "Admin PIN not configured" Error (HTTP 500)

**Cause**: ADMIN_PIN_HASH environment variable is empty or not set

**Solution**:
1. Generate a PIN hash (see [Generating a PIN Hash](#generating-a-pin-hash))
2. Set the environment variable
3. Restart the application
4. Verify it's set: `echo $ADMIN_PIN_HASH`

## Security Checklist

Before deploying to production, verify:

- [ ] `ADMIN_PIN_HASH` is set and uses a strong PIN
- [ ] `JENKINS_URL`, `JENKINS_USER`, and `JENKINS_API_TOKEN` are set
- [ ] Credentials are NOT stored in version control
- [ ] `.env` file is in `.gitignore`
- [ ] HTTPS is enabled in production
- [ ] Network access controls are configured
- [ ] Admin access is limited to authorized personnel
- [ ] Credentials rotation schedule is established
- [ ] Backup procedures include credential recovery
- [ ] Monitoring and alerting are configured for failed auth attempts

## Testing Security Configuration

### Test Admin PIN Authentication

```bash
# Without PIN (should fail with 401)
curl -X GET http://localhost:8000/api/v1/admin/settings

# With wrong PIN (should fail with 403)
curl -X GET http://localhost:8000/api/v1/admin/settings \
  -H "X-Admin-PIN: wrong-pin"

# With correct PIN (should succeed with 200)
curl -X GET http://localhost:8000/api/v1/admin/settings \
  -H "X-Admin-PIN: 1234"
```

### Test Jenkins Credentials

```python
# Run in Python REPL or script
from app.utils.security import CredentialsManager

# Test validation
is_valid = CredentialsManager.validate_jenkins_credentials()
print(f"Credentials configured: {is_valid}")

# Test retrieval
if is_valid:
    url, user, token = CredentialsManager.get_jenkins_credentials()
    print(f"URL: {url}")
    print(f"User: {user}")
    print(f"Token: {'*' * len(token)}")  # Don't print actual token
```

## Additional Resources

- [Security Design Document](../fixes/code-review-fixes.md)
- [FastAPI Security Best Practices](https://fastapi.tiangolo.com/tutorial/security/)
- [OWASP Security Guidelines](https://owasp.org/)

## Support

For security-related issues or questions:
1. Check the [Troubleshooting](#troubleshooting) section
2. Review application logs
3. Contact the development team (do NOT share credentials)

---

**Last Updated**: 2024
**Version**: 1.0
