# Migration Guides

This directory contains migration guides for upgrading between different versions of the Regression Tracker Web application.

## Available Guides

### PR #18 Migration Guide
- **[pr18-migration-guide.md](pr18-migration-guide.md)** - Migrate to path-based module tracking
- **Breaking Changes**: Module breakdown API response format
- **Required**: Database migration and backfill script
- **Recommended For**: All deployments upgrading to PR #18 or later

### Redis Migration
- **[redis-migration.md](redis-migration.md)** - Migrate from in-memory to Redis caching
- **[redis-update-steps.md](redis-update-steps.md)** - Step-by-step Redis setup instructions
- **Benefits**: Better performance in production with multiple workers
- **Recommended For**: Production deployments with Gunicorn

---

## Migration Workflow

When upgrading to a new version:

1. **Review breaking changes** in the [changelog](../changelog/)
2. **Read relevant migration guide** from this directory
3. **Backup database** before applying migrations
4. **Run database migrations**: `alembic upgrade head`
5. **Run backfill scripts** if mentioned in migration guide
6. **Test in staging environment** before production
7. **Update environment variables** as needed

---

## Quick Reference

### Database Migrations
```bash
# View current migration status
alembic current

# View migration history
alembic history

# Upgrade to latest
alembic upgrade head

# Rollback one migration
alembic downgrade -1
```

### Environment Updates
Check migration guides for new environment variables and update your `.env` file accordingly.

---

## Navigation

- [← Back to Documentation Index](../README.md)
- [Changelog →](../changelog/README.md)
- [Deployment Guides →](../deployment/)
