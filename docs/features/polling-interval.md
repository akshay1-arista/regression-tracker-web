# Polling Interval Configuration

The Regression Tracker Web Application supports automatic polling of Jenkins for new test results. The polling interval can be configured flexibly using hours as the base unit.

## Configuration

Set the `POLLING_INTERVAL_HOURS` environment variable in your `.env` file:

```bash
# Examples:
POLLING_INTERVAL_HOURS=12      # 12 hours (default, recommended)
POLLING_INTERVAL_HOURS=1       # 1 hour
POLLING_INTERVAL_HOURS=24      # 1 day
POLLING_INTERVAL_HOURS=168     # 1 week
POLLING_INTERVAL_HOURS=0.5     # 30 minutes
POLLING_INTERVAL_HOURS=0.25    # 15 minutes
```

## Common Intervals

| Interval | Hours Value | Use Case |
|----------|-------------|----------|
| 15 minutes | `0.25` | Development/testing |
| 30 minutes | `0.5` | Frequent updates |
| 1 hour | `1` | Active development |
| 6 hours | `6` | Standard polling |
| 12 hours | `12` | **Default** - Balanced |
| 1 day | `24` | Daily updates |
| 1 week | `168` | Weekly summaries |

## Migration from POLLING_INTERVAL_MINUTES

If you're upgrading from a previous version that used `POLLING_INTERVAL_MINUTES`, your old setting will continue to work automatically. The system provides backwards compatibility.

To migrate to the new format:

1. **Automatic Migration (Recommended)**:
   ```bash
   cd /opt/regression-tracker-web
   python3 scripts/migrate_polling_interval.py
   ```

2. **Manual Migration**:
   - Update your `.env` file:
     ```bash
     # Old (still works)
     POLLING_INTERVAL_MINUTES=720

     # New (recommended)
     POLLING_INTERVAL_HOURS=12
     ```
   - Restart the service:
     ```bash
     sudo systemctl restart regression-tracker
     ```

## Dynamic Updates

You can update the polling interval without restarting the service using the Admin API or web interface. Changes take effect immediately.

## Default Value

If no polling interval is configured, the system defaults to **12 hours**.

## Disabling Auto-Polling

To disable automatic polling entirely:

```bash
AUTO_UPDATE_ENABLED=false
```

You can still manually trigger Jenkins polling through the web interface.
