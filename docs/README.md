# Regression Tracker Web - Documentation

Welcome to the documentation for the Regression Tracker Web application. This directory contains comprehensive guides, references, and migration instructions.

## 📚 Documentation Structure

### 🚀 [Deployment](deployment/)
Guides for deploying and running the application:
- **[QUICKSTART.md](deployment/QUICKSTART.md)** - Quick setup guide for new deployments
- **[PRODUCTION.md](deployment/PRODUCTION.md)** - Production deployment with Gunicorn
- **[TESTING.md](deployment/TESTING.md)** - Testing strategies and best practices

### ✨ [Features](features/)
Documentation for specific features:
- **[polling-interval.md](features/polling-interval.md)** - Jenkins polling interval configuration
- **[priority-filtering-search.md](features/priority-filtering-search.md)** - Priority filtering and global search
- **[parent-job-tracking.md](features/parent-job-tracking.md)** - Parent job tracking functionality
- **[version-filtering.md](features/version-filtering.md)** - Version filtering capabilities
- **[version-hierarchy.md](features/version-hierarchy.md)** - Version hierarchy system
- **[version-tracking.md](features/version-tracking.md)** - Version tracking features

### 🔧 [Fixes](fixes/)
Bug fixes and code improvements:
- **[code-review-fixes.md](fixes/code-review-fixes.md)** - Historical code review fixes
- **[code-review-fixes-general.md](fixes/code-review-fixes-general.md)** - General code review improvements
- **[general-fixes-summary.md](fixes/general-fixes-summary.md)** - Summary of general fixes
- **[metadata-bugfix.md](fixes/metadata-bugfix.md)** - Metadata-related bug fixes
- **[polling-logic-fix.md](fixes/polling-logic-fix.md)** - Jenkins polling logic fixes

### 📋 [Changelog](changelog/)
Detailed change logs and PR summaries:
- **[PR #18](changelog/pr-18-breaking-changes.md)** - Breaking changes (Module breakdown API)
- **[PR #17](changelog/pr-17-code-review.md)** - Code review fixes
- **[PR #15](changelog/pr-15-fixes.md)** - Bug fixes
- **[PR #12](changelog/pr-12-fixes.md)** - Bug fixes
- **[PR #9](changelog/pr-09-fixes.md)** - Bug fixes
- **[PR #8](changelog/pr-08-fixes.md)** - Bug fixes
- **[Phase 5](changelog/phase-5-summary.md)** - Testing & Documentation phase
- **[PR Template](changelog/pr-description-template.md)** - PR description template

### 🔄 [Migration](migration/)
Version upgrade and migration guides:
- **[pr18-migration-guide.md](migration/pr18-migration-guide.md)** - Migrate to PR #18 (path-based modules)
- **[redis-migration.md](migration/redis-migration.md)** - Migrate to Redis caching
- **[redis-update-steps.md](migration/redis-update-steps.md)** - Step-by-step Redis setup

### 📖 [Guides](guides/)
User and admin guides:
- **[scripts-usage.md](guides/scripts-usage.md)** - How to use utility scripts
- **[security-setup.md](guides/security-setup.md)** - Security configuration guide
- **[legacy-test-issues.md](guides/legacy-test-issues.md)** - Known test issues and workarounds

---

## 🎯 Quick Links

### For New Users
1. Start with [QUICKSTART.md](deployment/QUICKSTART.md)
2. Review [Feature Documentation](features/)
3. Understand [Security Setup](guides/security-setup.md)

### For Developers
1. Review [CLAUDE.md](../CLAUDE.md) for AI assistant guidance
2. Check [Testing Guide](deployment/TESTING.md)
3. Read [Scripts Usage](guides/scripts-usage.md)

### For Upgrading
1. Check [Changelog](changelog/) for changes
2. Read relevant [Migration Guides](migration/)
3. Review breaking changes in PR summaries

---

## 🔍 Finding Documentation

- **Deployment**: [deployment/](deployment/)
- **Features**: [features/](features/)
- **Fixes**: [fixes/](fixes/)
- **Changelog**: [changelog/](changelog/)
- **Migration**: [migration/](migration/)
- **Guides**: [guides/](guides/)

---

## 📝 Additional Resources

- **Main README**: [../README.md](../README.md)
- **API Documentation**: http://localhost:8000/docs (when running)
- **CLAUDE.md**: [../CLAUDE.md](../CLAUDE.md) - AI assistant instructions

---

## 🤝 Contributing

When adding new documentation:
1. Place files in the appropriate directory
2. Update the relevant README.md index
3. Use clear, descriptive filenames (kebab-case)
4. Link related documents together

---

## 📊 Documentation Status

- ✅ Deployment guides complete
- ✅ Feature documentation complete
- ✅ Migration guides complete
- ✅ Changelog organized
- ✅ Fix documentation organized

Last updated: 2026-01-23
