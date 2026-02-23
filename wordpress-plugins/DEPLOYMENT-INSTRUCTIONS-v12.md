# Medical Memory v12.0.0 - Deployment Instructions

## 🎯 Τι Περιλαμβάνει η v12.0.0

### ✅ Νέα Features (Production-Ready)

1. **Dose Instances Table** (`tkc_mm_doses`)
   - Μεμονωμένες δόσεις με unique constraint
   - Atomic locking για anti-duplicate
   - Status tracking: pending → sending → sent → taken/missed/failed

2. **Automatic Dose Generation**
   - Pre-generates doses για 30 ημέρες μπροστά
   - Auto-regeneration όταν κάνετε update φάρμακο
   - Daily top-up cron job

3. **Admin Diagnostics Dashboard**
   - Cron health monitoring
   - OneSignal subscription status
   - Dose statistics
   - Notification audit trail
   - Test push button
   - Manual cron trigger

4. **Comprehensive Logging**
   - `tkc_mm_cron_log` - Cron execution tracking
   - `tkc_mm_notification_log` - Notification audit trail
   - Performance metrics (execution time, success rate)

5. **Production-Grade Cron**
   - Atomic locking (no more duplicates)
   - Retry logic (3 attempts before marking as failed)
   - Error handling and logging
   - Multiple cron jobs (check, generate, cleanup)

---

## 📋 Deployment Steps

### Step 1: Backup

**ΚΡΙΤΙΚΟ:** Πριν κάνετε οτιδήποτε, κάντε backup!

```bash
# Backup database
mysqldump -u [user] -p [database] > medical_memory_backup_$(date +%Y%m%d).sql

# Backup plugin folder
cd /path/to/wordpress/wp-content/plugins
tar -czf medical_memory_backup_$(date +%Y%m%d).tar.gz autoanosis-medical-memory/
```

### Step 2: Upload Plugin

1. Πηγαίνετε στο WordPress Admin → Plugins → Add New → Upload Plugin
2. Επιλέξτε το αρχείο `autoanosis-medical-memory-v12.0.0.zip`
3. Πατήστε "Install Now"
4. **ΜΗΝ ενεργοποιήσετε ακόμα!**

### Step 3: Deactivate Old Version

1. Πηγαίνετε στο Plugins → Installed Plugins
2. Βρείτε το "Autoanosis Medical Memory" (v11.0.2)
3. Πατήστε "Deactivate"
4. **ΜΗΝ διαγράψετε!** (απλά deactivate)

### Step 4: Delete Old Plugin Files

Μέσω FTP/SFTP:

```bash
cd /path/to/wordpress/wp-content/plugins
rm -rf autoanosis-medical-memory/
```

### Step 5: Upload v12 via FTP (Alternative)

Αν το upload μέσω WordPress δεν δουλεύει:

```bash
# Unzip locally
unzip autoanosis-medical-memory-v12.0.0.zip

# Upload via FTP to:
/wp-content/plugins/autoanosis-medical-memory/
```

### Step 6: Activate v12

1. Πηγαίνετε στο Plugins → Installed Plugins
2. Βρείτε το "Autoanosis Medical Memory" (v12.0.0)
3. Πατήστε "Activate"

**Τι θα γίνει αυτόματα:**
- Δημιουργία νέων tables (doses, onesignal_tokens, notification_log, cron_log)
- Migration δεδομένων από device_subscriptions
- Generation doses για όλα τα active medications
- Scheduling cron jobs

### Step 7: Verify Database

Πηγαίνετε στο phpMyAdmin και ελέγξτε ότι δημιουργήθηκαν:

- `tkc_mm_doses` (με doses για τα υπάρχοντα φάρμακα)
- `tkc_mm_onesignal_tokens` (με migrated data)
- `tkc_mm_notification_log` (άδειο)
- `tkc_mm_cron_log` (άδειο)

### Step 8: Configure OneSignal (αν δεν είναι ήδη)

1. Πηγαίνετε στο Medical Memory → Settings
2. Συμπληρώστε:
   - **App ID**: `8cc1f444-7ddf-498c-962b-8d28d1b144ce`
   - **REST API Key**: `os_v2_app_rta7ird535eyzfrlruundmkez2rj34rlljduqtmxkfyxw5uesctjzifyqyucygqmll4hgocedohhzs2t2da6ixub4q3crdb3bj35tzi`
   - **Enable Push**: ✅ Checked
3. Save Changes

### Step 9: Check Diagnostics

1. Πηγαίνετε στο Medical Memory → **Diagnostics** (νέο menu!)
2. Ελέγξτε:
   - **Cron Health**: Πρέπει να δείτε "✅ Active" για όλα τα jobs
   - **OneSignal Status**: Πρέπει να δείτε τα subscriptions
   - **Dose Statistics**: Πρέπει να δείτε pending doses

### Step 10: Test Push Notification

1. Στο Diagnostics page, scroll down στο "Test Tools"
2. Πατήστε "Send Test Push to Me"
3. Πρέπει να λάβετε notification στη συσκευή σας

### Step 11: Configure SiteGround Cron

**ΚΡΙΤΙΚΟ:** Αυτό είναι το πιο σημαντικό βήμα!

#### Option A: SiteGround Site Tools (Recommended)

1. Μπείτε στο SiteGround Site Tools
2. Πηγαίνετε στο **Devs → Cron Jobs**
3. Προσθέστε νέο Cron Job:
   - **Type**: Custom
   - **Command**: 
     ```bash
     curl -s https://autoanosis.com/wp-cron.php?doing_wp_cron >/dev/null 2>&1
     ```
   - **Interval**: Every 1 minute
   - **Enabled**: ✅ Yes
4. Save

#### Option B: cPanel Cron Jobs

1. Μπείτε στο cPanel
2. Πηγαίνετε στο **Advanced → Cron Jobs**
3. Προσθέστε νέο Cron Job:
   - **Minute**: `*`
   - **Hour**: `*`
   - **Day**: `*`
   - **Month**: `*`
   - **Weekday**: `*`
   - **Command**: 
     ```bash
     wget -q -O - https://autoanosis.com/wp-cron.php?doing_wp_cron >/dev/null 2>&1
     ```
4. Add Cron Job

#### Verification

Περιμένετε 2-3 λεπτά και μετά:

1. Πηγαίνετε στο Medical Memory → Diagnostics
2. Ελέγξτε το "Cron Health" section
3. Πρέπει να δείτε:
   - **Last Run**: Πριν λίγα λεπτά
   - **Total Runs**: > 0
   - **Successful Runs**: > 0

### Step 12: Test End-to-End

1. Προσθέστε ένα test medication με ώρα **5 λεπτά από τώρα**
2. Περιμένετε 5 λεπτά
3. Πρέπει να λάβετε push notification
4. Ελέγξτε το Diagnostics → Recent Notifications
5. Πρέπει να δείτε το notification με status "sent"

---

## 🔍 Troubleshooting

### Πρόβλημα: Δεν δημιουργήθηκαν τα νέα tables

**Λύση:**
```sql
-- Run the schema manually
-- Copy from /home/ubuntu/medical-memory-schema-v12.sql
```

### Πρόβλημα: Δεν υπάρχουν doses στο doses table

**Λύση:**
1. Πηγαίνετε στο Medical Memory → Diagnostics
2. Πατήστε "Manually Run Cron Now"
3. Ή μέσω phpMyAdmin:
```sql
-- Check if medications exist
SELECT * FROM tkc_mm_medications WHERE active = 1;

-- Manually trigger dose generation via WordPress
-- Go to any medication and click "Edit" → "Update"
```

### Πρόβλημα: Cron δεν τρέχει

**Ελέγξτε:**

1. **SiteGround Cron configured?**
   - Site Tools → Devs → Cron Jobs
   - Πρέπει να βλέπετε το cron job

2. **WordPress Cron enabled?**
   ```php
   // Check wp-config.php
   // Make sure this is NOT set:
   // define('DISABLE_WP_CRON', true);
   ```

3. **Cron URL accessible?**
   ```bash
   curl -I https://autoanosis.com/wp-cron.php
   # Should return 200 OK
   ```

### Πρόβλημα: Notifications δεν στέλνονται

**Ελέγξτε:**

1. **OneSignal credentials correct?**
   - Medical Memory → Settings
   - App ID και API Key σωστά

2. **User subscribed?**
   - Medical Memory → Diagnostics → OneSignal Status
   - Πρέπει να βλέπετε το subscription

3. **Doses pending?**
   - Medical Memory → Diagnostics → Dose Statistics
   - Πρέπει να υπάρχουν pending doses

4. **Check logs:**
   - Medical Memory → Diagnostics → Recent Notifications
   - Δείτε αν υπάρχουν errors

### Πρόβλημα: Duplicate notifications

**Αυτό ΔΕΝ πρέπει να συμβεί στη v12!**

Αν συμβεί:
1. Ελέγξτε το Diagnostics → Dose Statistics
2. Αν βλέπετε doses με status "sending" για πολλή ώρα:
```sql
-- Reset stuck doses
UPDATE tkc_mm_doses 
SET status = 'pending', attempts = 0 
WHERE status = 'sending' 
AND updated_at < DATE_SUB(NOW(), INTERVAL 5 MINUTE);
```

---

## 📊 Monitoring

### Daily Checks

1. **Cron Health**
   - Medical Memory → Diagnostics
   - Ελέγξτε "Cron Health (Last 24 Hours)"
   - Πρέπει να βλέπετε successful runs

2. **Notification Success Rate**
   - Ελέγξτε "Recent Notifications"
   - Πρέπει να βλέπετε "sent" status

3. **Dose Statistics**
   - Ελέγξτε "Dose Statistics (Last 7 Days)"
   - Πρέπει να βλέπετε pending/sent/taken doses

### Weekly Checks

1. **Database Size**
   ```sql
   SELECT 
       table_name,
       ROUND(((data_length + index_length) / 1024 / 1024), 2) AS size_mb
   FROM information_schema.TABLES
   WHERE table_schema = DATABASE()
   AND table_name LIKE 'tkc_mm_%'
   ORDER BY size_mb DESC;
   ```

2. **Old Doses Cleanup**
   - Automatic (weekly cron)
   - Ελέγξτε Diagnostics → Cron Health → cleanup_doses

---

## 🚀 Performance

### Expected Performance

- **Cron execution time**: < 100ms (για 10-20 doses)
- **Notification delivery**: < 2 seconds
- **Database queries**: < 5 queries per cron run

### Optimization

Αν το cron αργεί:

1. **Add indexes** (ήδη υπάρχουν στη v12)
2. **Limit dose window** (τώρα είναι ±2 minutes)
3. **Increase cron interval** (από 1 minute σε 2 minutes)

---

## 📝 Changelog

### v12.0.0 (Production-Ready)

**NEW:**
- ✅ Dose instances table με atomic locking
- ✅ Automatic dose generation (30 days ahead)
- ✅ Admin diagnostics dashboard
- ✅ Comprehensive logging (cron + notifications)
- ✅ Test push button
- ✅ Manual cron trigger
- ✅ OneSignal subscription tracking
- ✅ Dose statistics

**FIXED:**
- ✅ Anti-duplicate με database unique constraint (όχι transients)
- ✅ Atomic status updates (no race conditions)
- ✅ Proper error handling και retry logic
- ✅ Performance indexes

**IMPROVED:**
- ✅ Server cron support (SiteGround)
- ✅ Better timezone handling
- ✅ Comprehensive error logging

### v11.0.2 (Previous)

- Basic cron με transients
- OneSignal integration
- UI/frontend working
- **Notifications δεν δούλευαν σταθερά**

---

## ⚠️ Important Notes

1. **Μην διαγράψετε το backup!** Κρατήστε το για 30 ημέρες.
2. **Ελέγξτε τα logs καθημερινά** για τις πρώτες 7 ημέρες.
3. **Το SiteGround cron είναι ΚΡΙΤΙΚΟ** - χωρίς αυτό, τίποτα δεν θα δουλέψει.
4. **Τα δεδομένα σας είναι ασφαλή** - όλα τα medications/adherence παραμένουν ίδια.

---

## 🎉 Success Criteria

Το σύστημα λειτουργεί σωστά όταν:

- ✅ Cron runs κάθε λεπτό (Diagnostics → Cron Health)
- ✅ Notifications στέλνονται εντός 1-2 λεπτών από τη scheduled time
- ✅ Δεν υπάρχουν duplicate notifications
- ✅ Test push button δουλεύει
- ✅ Recent Notifications δείχνει "sent" status
- ✅ Dose Statistics δείχνει pending/sent/taken doses

---

## 📞 Support

Αν χρειαστείτε βοήθεια:

1. Ελέγξτε το Diagnostics dashboard πρώτα
2. Ελέγξτε τα logs (Recent Notifications, Cron Health)
3. Στείλτε screenshot από το Diagnostics page

---

**Version**: 12.0.0  
**Date**: 2026-02-23  
**Author**: Autoanosis Team  
**Cost**: €0 (100% δωρεάν)
