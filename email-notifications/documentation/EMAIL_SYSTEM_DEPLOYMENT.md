# Email Notification System - Deployment Guide

## ✅ Τι Έχει Υλοποιηθεί

### 1. Backend Email Service (Brevo API)
- ✅ `EmailService` class με Brevo API integration
- ✅ `send_digest_emails()` method για αποστολή digest emails
- ✅ `get_new_decisions()` method για φιλτράρισμα νέων αποφάσεων
- ✅ `get_subscribed_users()` method για εύρεση subscribed users
- ✅ HTML email template (`dip/email_template.html`)
- ✅ Support για daily και weekly frequency

### 2. API Endpoints
- ✅ `POST /admin/send-daily-digests` - Στέλνει daily digest emails
- ✅ `POST /admin/send-weekly-digests` - Στέλνει weekly digest emails
- ✅ Authentication με `x-admin-token` header

### 3. Content Filtering
Τα emails περιέχουν ΜΟΝΟ αποφάσεις που σχετίζονται με:
- ✅ Υγεία (νοσοκομεία, φάρμακα, ΕΟΠΥΥ, ιατρικά)
- ✅ Συντάξεις (συνταξιοδότηση, συνταξιούχοι)
- ✅ ΚΕΠΑ (αναπηρία, ΑΜΕΑ)
- ✅ Κοινωνική πρόνοια (επιδόματα, βοηθήματα)

Αποκλείονται:
- ❌ Διοικητικές αποφάσεις (μισθοδοσία, προμήθειες, συμβάσεις)
- ❌ Προσλήψεις και διορισμοί
- ❌ Εργοδοτικές εισφορές

### 4. Email Template
Professional HTML email template με:
- ✅ Autoanosis branding
- ✅ Λίστα αποφάσεων με links
- ✅ Ημερομηνία και πρωτόκολλο για κάθε απόφαση
- ✅ CTA button για το portal
- ✅ Unsubscribe link
- ✅ Responsive design

## 📋 Deployment Checklist

### Βήμα 1: Verify Backend Deployment ✅
Το backend έχει γίνει deploy στο Render με τις νέες αλλαγές.

```bash
# Test health endpoint
curl https://dip-backend-puof.onrender.com/health
# Expected: {"ok":true,"service":"DIP"}
```

### Βήμα 2: Verify Environment Variables
Στο Render Dashboard, έλεγξε ότι υπάρχουν:
- ✅ `BREVO_API_KEY` - API key για Brevo email service
- ✅ `DIP_ADMIN_TOKEN` - Admin token για authentication
- ✅ `SMTP_FROM_EMAIL` - Email address για sender (optional)
- ✅ `SMTP_FROM_NAME` - Sender name (optional, default: "DIP Platform")

### Βήμα 3: Test Email Endpoints

#### Option A: Using Test Script
```bash
./test_email_digest.sh YOUR_ADMIN_TOKEN
```

#### Option B: Manual Testing
```bash
# Test daily digest
curl -X POST https://dip-backend-puof.onrender.com/admin/send-daily-digests \
  -H "x-admin-token: YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json"

# Expected response:
# {"success":true,"emails_sent":1}
```

### Βήμα 4: Verify Email Delivery
1. Έλεγξε το inbox του `nipeshoes@gmail.com`
2. Αναζήτησε email με subject: "Νέες Κυβερνητικές Αποφάσεις - Ημερήσια Ενημέρωση"
3. Επιβεβαίωσε ότι:
   - Το email φαίνεται σωστά (HTML rendering)
   - Τα links λειτουργούν
   - Οι αποφάσεις είναι σχετικές (υγεία, συντάξεις, ΚΕΠΑ, κοινωνική πρόνοια)

### Βήμα 5: Setup Cron Job

#### Recommended: cron-job.org (Free & Reliable)

1. **Δημιουργία λογαριασμού**
   - Πήγαινε στο https://cron-job.org/en/
   - Sign up (δωρεάν)
   - Verify email

2. **Daily Digest Cron Job**
   - Title: `DIP Daily Digest Emails`
   - URL: `https://dip-backend-puof.onrender.com/admin/send-daily-digests`
   - Method: `POST`
   - Schedule: Every day at `09:00` (Athens time)
   - Headers: 
     - `x-admin-token`: `YOUR_ADMIN_TOKEN`
   - Timeout: `60 seconds`
   - Enable: ✅

3. **Weekly Digest Cron Job**
   - Title: `DIP Weekly Digest Emails`
   - URL: `https://dip-backend-puof.onrender.com/admin/send-weekly-digests`
   - Method: `POST`
   - Schedule: Every Monday at `09:00` (Athens time)
   - Headers: 
     - `x-admin-token`: `YOUR_ADMIN_TOKEN`
   - Timeout: `60 seconds`
   - Enable: ✅

## 🔍 Monitoring & Troubleshooting

### Check Render Logs
```
1. Go to https://dashboard.render.com
2. Select "dip-backend" service
3. Click "Logs" tab
4. Look for:
   - "📧 Found X new decisions for daily digest"
   - "👥 Found X users subscribed to daily digest"
   - "✅ Sent X daily digest emails"
```

### Common Issues

#### No emails sent (emails_sent: 0)
**Possible causes:**
1. No users with `email_enabled: true` in database
2. No new decisions in the last 24 hours (for daily) or 7 days (for weekly)
3. User email_address is null or empty

**Solution:**
```bash
# Check user preferences
curl https://dip-backend-puof.onrender.com/api/preferences/561cd1d7-c2b9-49e3-83d7-465012fa50ee

# Should show:
# {
#   "email_enabled": true,
#   "email_address": "nipeshoes@gmail.com",
#   "frequency": "daily"
# }
```

#### Authentication failed (401)
**Cause:** Wrong admin token

**Solution:** Get the correct token from Render environment variables

#### Emails go to spam
**Cause:** Brevo sender reputation or email content

**Solutions:**
1. Add `noreply@autoanosis.com` to contacts
2. Check Brevo dashboard for delivery status
3. Verify SPF/DKIM records for sender domain

#### Render service is sleeping
**Cause:** Free tier sleeps after 15 minutes of inactivity

**Impact:** First cron job call will take 30-60 seconds to wake up the service

**Solution:** Upgrade to paid plan ($7/month) to prevent sleeping

## 📊 Expected Behavior

### Daily Digest (9:00 AM every day)
1. Cron job calls `/admin/send-daily-digests`
2. Backend queries database for decisions from last 24 hours
3. Filters decisions by health/pensions/KEPA/social keywords
4. Gets all users with `email_enabled: true` and `frequency: "daily"`
5. Sends one email to each user with list of new decisions
6. Returns `{"success": true, "emails_sent": N}`

### Weekly Digest (9:00 AM every Monday)
1. Cron job calls `/admin/send-weekly-digests`
2. Backend queries database for decisions from last 7 days
3. Filters decisions by health/pensions/KEPA/social keywords
4. Gets all users with `email_enabled: true` and `frequency: "weekly"`
5. Sends one email to each user with list of new decisions
6. Returns `{"success": true, "emails_sent": N}`

## 🎯 Success Criteria

- [x] Backend deployed with email functionality
- [ ] Test email received successfully
- [ ] Cron job configured and enabled
- [ ] User receives daily emails at 9:00 AM
- [ ] Email content is relevant (health, pensions, KEPA, social)
- [ ] Unsubscribe link works
- [ ] No spam issues

## 📝 Next Steps After Deployment

1. **Monitor for 1 week** - Check that emails arrive daily at 9:00 AM
2. **User feedback** - Ask user if content is relevant
3. **Adjust filtering** - If needed, refine keyword filters
4. **Add more users** - Once confirmed working, promote to other users
5. **Analytics** - Track email open rates in Brevo dashboard

## 🔗 Important Links

- Backend: https://dip-backend-puof.onrender.com
- Render Dashboard: https://dashboard.render.com
- Brevo Dashboard: https://app.brevo.com
- Cron-job.org: https://cron-job.org/en/
- WordPress Portal: https://autoanosis.com/κυβερνητικές-αποφάσεις/
- Settings Page: https://autoanosis.com/ρυθμίσεις-ειδοποιήσεων/

## 🆘 Support

If something doesn't work:
1. Check Render logs for errors
2. Verify environment variables are set
3. Test endpoints manually with curl
4. Check Brevo dashboard for email delivery status
5. Verify user preferences in database
