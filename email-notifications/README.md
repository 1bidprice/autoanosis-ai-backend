# Email Notification System - Complete Project Documentation

## 📋 Project Overview

**Project Name:** DIP Portal Email Notification System  
**Repository:** 1bidprice/dip-backend  
**Deployment:** Render (https://dip-backend-puof.onrender.com)  
**Status:** ✅ Completed and Deployed  
**Date:** February 2026

### Purpose
Automated email notification system that sends daily and weekly digests of Greek government decisions to subscribers, focusing on health, pensions, KEPA, and social welfare topics.

---

## 🎯 Requirements Analysis

### User Requirements
1. **Automated Email Sending:** Daily and weekly digest emails
2. **Content Filtering:** Only relevant government decisions (health, pensions, social welfare)
3. **Professional Design:** Branded Autoanosis email template
4. **Reliability:** Must run automatically without manual intervention
5. **Scalability:** Support multiple subscribers
6. **Zero Maintenance:** Set it and forget it

### Technical Requirements
1. **Email Service:** Professional email delivery (Brevo API)
2. **Database Integration:** PostgreSQL with source_events table
3. **API Endpoints:** Secure admin endpoints for triggering emails
4. **Automation:** Scheduled execution (GitHub Actions)
5. **Security:** Token-based authentication
6. **Monitoring:** Execution logs and error handling

---

## 🏗️ Architecture Design

### System Components

```
┌─────────────────────────────────────────────────────────────┐
│                     GitHub Actions (Scheduler)               │
│  ┌──────────────────┐         ┌──────────────────┐         │
│  │  Daily Digest    │         │  Weekly Digest   │         │
│  │  Cron: 0 7 * * * │         │  Cron: 0 7 * * 1 │         │
│  └────────┬─────────┘         └────────┬─────────┘         │
└───────────┼──────────────────────────────┼─────────────────┘
            │                              │
            │ HTTP POST                    │ HTTP POST
            │ x-admin-token: SECRET        │ x-admin-token: SECRET
            ▼                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   FastAPI Backend (Render)                   │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  API Endpoints                                        │  │
│  │  - POST /admin/send-daily-digests                    │  │
│  │  - POST /admin/send-weekly-digests                   │  │
│  └────────┬─────────────────────────────────────────────┘  │
│           │                                                  │
│  ┌────────▼─────────────────────────────────────────────┐  │
│  │  Email Service (email_service.py)                    │  │
│  │  - get_subscribers()                                 │  │
│  │  - get_recent_decisions(days)                        │  │
│  │  - filter_relevant_decisions()                       │  │
│  │  - send_digest_email()                               │  │
│  └────────┬─────────────────────────────────────────────┘  │
└───────────┼──────────────────────────────────────────────────┘
            │
            ├─────────────┐
            │             │
            ▼             ▼
    ┌──────────────┐  ┌──────────────┐
    │  PostgreSQL  │  │  Brevo API   │
    │   Database   │  │ Email Service│
    └──────────────┘  └──────────────┘
```

### Data Flow

1. **GitHub Actions Trigger:** Cron schedule triggers workflow
2. **API Request:** Workflow sends authenticated POST request to backend
3. **Subscriber Retrieval:** Backend fetches active subscribers from database
4. **Decision Fetching:** Queries source_events table for recent decisions
5. **Content Filtering:** Filters decisions by relevance (keywords, categories)
6. **Email Generation:** Creates HTML email from template
7. **Email Delivery:** Sends via Brevo API to all subscribers
8. **Response:** Returns success/failure status

---

## 📁 Project Structure

```
dip-backend/
├── .github/
│   └── workflows/
│       ├── daily-digest.yml          # Daily automation
│       └── weekly-digest.yml         # Weekly automation
├── dip/
│   ├── app/
│   │   ├── main.py                   # API endpoints
│   │   ├── email_service.py          # Email logic
│   │   └── models.py                 # Database models
│   └── email_template.html           # Email HTML template
└── .env                               # Environment variables
```

---

## 🔧 Implementation Details

### 1. Email Service (`email_service.py`)

**Key Functions:**

```python
async def get_subscribers(session: AsyncSession) -> List[str]
```
- Fetches all active subscriber emails from database
- Returns list of email addresses

```python
async def get_recent_decisions(session: AsyncSession, days: int) -> List[SourceEvent]
```
- Queries source_events table for decisions within specified days
- Filters by issue_date
- Returns list of SourceEvent objects

```python
def filter_relevant_decisions(decisions: List[SourceEvent]) -> List[SourceEvent]
```
- Filters decisions by relevance using keywords
- **Included keywords:** υγεία, υγειονομικ, νοσοκομε, ασφάλιση, σύνταξη, συνταξ, ΚΕΠΑ, κοινωνικ, πρόνοια
- **Excluded keywords:** μισθοδοσία, προμήθεια, σύμβαση, ανάθεση
- Returns filtered list

```python
async def send_digest_email(to_email: str, decisions: List[SourceEvent], period: str)
```
- Loads HTML template
- Populates with decision data
- Sends via Brevo API
- Returns success/failure boolean

### 2. API Endpoints (`main.py`)

```python
@app.post("/admin/send-daily-digests")
async def send_daily_digests(admin_token: str = Header(None, alias="x-admin-token"))
```
- Validates admin token
- Fetches decisions from last 24 hours
- Sends emails to all subscribers
- Returns: `{"success": true, "emails_sent": count}`

```python
@app.post("/admin/send-weekly-digests")
async def send_weekly_digests(admin_token: str = Header(None, alias="x-admin-token"))
```
- Validates admin token
- Fetches decisions from last 7 days
- Sends emails to all subscribers
- Returns: `{"success": true, "emails_sent": count}`

### 3. GitHub Actions Workflows

**Daily Digest (`daily-digest.yml`):**
```yaml
on:
  schedule:
    - cron: '0 7 * * *'  # 09:00 Athens time (UTC+2)
  workflow_dispatch:      # Manual trigger support

jobs:
  send-daily-digest:
    runs-on: ubuntu-latest
    steps:
      - name: Send daily digest emails
        run: |
          curl -X POST https://dip-backend-puof.onrender.com/admin/send-daily-digests \
            -H "x-admin-token: ${{ secrets.DIP_ADMIN_TOKEN }}" \
            -H "Content-Type: application/json"
```

**Weekly Digest (`weekly-digest.yml`):**
```yaml
on:
  schedule:
    - cron: '0 7 * * 1'  # Every Monday 09:00 Athens time
  workflow_dispatch:
```

### 4. Email Template

**Features:**
- Autoanosis branding with logo
- Responsive HTML design
- Decision list with:
  - Title (clickable link to Diavgeia)
  - Issue date
  - Protocol number
- Call-to-action button
- Unsubscribe link
- Professional footer

---

## 🚀 Deployment Process

### Step 1: Backend Deployment (Render)

1. **Repository:** Connected to 1bidprice/dip-backend
2. **Auto-deploy:** Enabled on main branch push
3. **Environment Variables:**
   - `DATABASE_URL`: PostgreSQL connection string
   - `BREVO_API_KEY`: Email service API key
   - `DIP_ADMIN_TOKEN`: Admin authentication token
4. **Health Check:** https://dip-backend-puof.onrender.com/health

### Step 2: GitHub Actions Setup

1. **Add Secret:** `DIP_ADMIN_TOKEN` in repository settings
2. **Upload Workflows:** Push `.github/workflows/*.yml` to main branch
3. **Verify:** Check Actions tab for scheduled runs

### Step 3: Testing

```bash
# Test daily digest
curl -X POST https://dip-backend-puof.onrender.com/admin/send-daily-digests \
  -H "x-admin-token: YOUR_TOKEN" \
  -H "Content-Type: application/json"

# Expected response
{"success":true,"emails_sent":1}
```

---

## 📊 Database Schema

### `source_events` Table

```sql
CREATE TABLE source_events (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    protocol_number VARCHAR(255),
    issue_date DATE,
    url TEXT,
    category VARCHAR(255),
    organization VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW()
);
```

### `subscribers` Table (Future)

```sql
CREATE TABLE subscribers (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    frequency VARCHAR(50) DEFAULT 'daily',  -- 'daily' or 'weekly'
    created_at TIMESTAMP DEFAULT NOW(),
    unsubscribe_token VARCHAR(255) UNIQUE
);
```

---

## 🔐 Security Considerations

1. **Token Authentication:** All admin endpoints require `x-admin-token` header
2. **Environment Variables:** Sensitive data stored in Render environment
3. **GitHub Secrets:** Admin token stored as encrypted secret
4. **Rate Limiting:** Consider implementing rate limits on endpoints
5. **Email Validation:** Validate subscriber emails before sending
6. **Unsubscribe:** Implement one-click unsubscribe mechanism

---

## 📈 Monitoring & Logging

### GitHub Actions Logs
- View execution history: https://github.com/1bidprice/dip-backend/actions
- Check workflow runs for errors
- Manual trigger for testing

### Render Logs
- Real-time logs: https://dashboard.render.com → dip-backend → Logs
- Filter by severity (INFO, WARNING, ERROR)
- Monitor API response times

### Email Delivery Metrics
- Brevo dashboard: Track delivery rates, opens, clicks
- Bounce handling: Monitor invalid email addresses
- Spam reports: Track user complaints

---

## 🧪 Testing Strategy

### Unit Tests
```python
# test_email_service.py
async def test_filter_relevant_decisions():
    decisions = [
        SourceEvent(title="Απόφαση για υγεία"),
        SourceEvent(title="Μισθοδοσία προσωπικού")
    ]
    filtered = filter_relevant_decisions(decisions)
    assert len(filtered) == 1
    assert "υγεία" in filtered[0].title
```

### Integration Tests
```python
async def test_send_daily_digests_endpoint():
    response = client.post(
        "/admin/send-daily-digests",
        headers={"x-admin-token": "test_token"}
    )
    assert response.status_code == 200
    assert response.json()["success"] == True
```

### Manual Testing
1. Trigger workflow manually from GitHub Actions
2. Check email inbox for digest
3. Verify email content and formatting
4. Test unsubscribe link
5. Confirm Diavgeia links work

---

## 🐛 Troubleshooting Guide

### Issue: Emails Not Sending

**Symptoms:** API returns success but no emails received

**Solutions:**
1. Check Brevo API key is valid
2. Verify subscriber emails in database
3. Check spam folder
4. Review Brevo dashboard for delivery status
5. Check Render logs for errors

### Issue: GitHub Actions Not Running

**Symptoms:** Scheduled workflows don't execute

**Solutions:**
1. Verify workflows are on main branch
2. Check DIP_ADMIN_TOKEN secret exists
3. Ensure repository has Actions enabled
4. Review workflow syntax (YAML validation)
5. Check GitHub Actions quota

### Issue: 401 Unauthorized

**Symptoms:** API returns 401 error

**Solutions:**
1. Verify DIP_ADMIN_TOKEN matches between Render and GitHub
2. Check header name is `x-admin-token` (lowercase)
3. Ensure token is not expired
4. Review Render environment variables

### Issue: No Recent Decisions

**Symptoms:** Email sent but contains no decisions

**Solutions:**
1. Check source_events table has recent data
2. Verify issue_date field is populated
3. Review filter keywords (may be too restrictive)
4. Check database connection
5. Adjust time window (increase days parameter)

---

## 🔄 Maintenance & Updates

### Regular Tasks
- **Weekly:** Review GitHub Actions execution logs
- **Monthly:** Check email delivery rates in Brevo
- **Quarterly:** Update filter keywords based on user feedback
- **Yearly:** Review and update email template design

### Scaling Considerations
1. **Subscriber Growth:** Implement batch email sending (Brevo limits)
2. **Database Performance:** Add indexes on issue_date, category
3. **Email Personalization:** Add user preferences (topics, frequency)
4. **Analytics:** Track email opens, clicks, conversions
5. **A/B Testing:** Test different subject lines, content formats

---

## 📚 Related Documentation

- **Brevo API Docs:** https://developers.brevo.com/
- **GitHub Actions Docs:** https://docs.github.com/en/actions
- **FastAPI Docs:** https://fastapi.tiangolo.com/
- **SQLAlchemy Docs:** https://docs.sqlalchemy.org/
- **Render Docs:** https://render.com/docs

---

## 🎓 Lessons Learned

### What Worked Well
1. **GitHub Actions:** Free, reliable, integrated with repository
2. **Brevo API:** Professional email delivery with good documentation
3. **Content Filtering:** Keyword-based filtering effectively removes noise
4. **HTML Templates:** Responsive design works across email clients
5. **Modular Architecture:** Easy to test and maintain

### Challenges Faced
1. **GitHub App Permissions:** Limited permissions for workflows and secrets
2. **Render Free Tier:** No built-in cron job support
3. **Email Template Compatibility:** Different email clients render HTML differently
4. **Time Zone Handling:** UTC vs Athens time for scheduling
5. **Database Schema:** Had to adapt to existing source_events structure

### Future Improvements
1. **User Preferences:** Allow subscribers to choose topics and frequency
2. **Email Analytics:** Track engagement metrics
3. **Content Summarization:** Use AI to summarize decisions
4. **Mobile App:** Push notifications in addition to emails
5. **Admin Dashboard:** Web UI for managing subscribers and viewing stats

---

## 👥 Team & Contributors

**Developer:** Manus AI Agent  
**Project Owner:** 1bidprice  
**Email Service:** Brevo  
**Hosting:** Render  
**Automation:** GitHub Actions

---

## 📄 License

This project is part of the Autoanosis DIP Portal system.

---

## 📞 Support

For issues or questions:
- **GitHub Issues:** https://github.com/1bidprice/dip-backend/issues
- **Email:** nipeshoes@gmail.com

---

**Last Updated:** February 22, 2026  
**Version:** 1.0.0  
**Status:** ✅ Production Ready
