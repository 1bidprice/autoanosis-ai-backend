# SiteGround Cron Setup Guide για Medical Memory v12

## 🎯 Γιατί Χρειάζεται Server Cron

Το WordPress WP-Cron **ΔΕΝ είναι αξιόπιστο** γιατί:
- Τρέχει μόνο όταν κάποιος επισκέπτεται το site
- Cached pages bypass το wp-cron.php
- Μπορεί να έχει delays 5-30 λεπτά

Για **ιατρικές ειδοποιήσεις** χρειαζόμαστε **server cron** που τρέχει κάθε λεπτό ανεξάρτητα από traffic.

---

## 📋 Setup Instructions

### Option 1: SiteGround Site Tools (Recommended)

#### Step 1: Login to SiteGround

1. Πηγαίνετε στο https://my.siteground.com/
2. Login με τα credentials σας
3. Επιλέξτε το website σας (autoanosis.com)

#### Step 2: Open Cron Jobs

1. Πατήστε **"Site Tools"**
2. Στο αριστερό menu, πηγαίνετε στο **"Devs"**
3. Πατήστε **"Cron Jobs"**

#### Step 3: Create New Cron Job

1. Πατήστε **"Create Cron Job"**
2. Συμπληρώστε:

**Name**: `Medical Memory Notifications`

**Type**: `Custom`

**Command**:
```bash
curl -s https://autoanosis.com/wp-cron.php?doing_wp_cron >/dev/null 2>&1
```

**Interval**: `Every 1 minute`

**Enabled**: ✅ Yes

3. Πατήστε **"Create"**

#### Step 4: Verify

Περιμένετε 2-3 λεπτά και μετά:

1. Πηγαίνετε στο WordPress Admin
2. Medical Memory → Diagnostics
3. Ελέγξτε το "Cron Health" section
4. Πρέπει να δείτε:
   - Last Run: Πριν λίγα λεπτά
   - Total Runs: > 0

---

### Option 2: cPanel (Alternative)

Αν δεν έχετε Site Tools, χρησιμοποιήστε cPanel:

#### Step 1: Login to cPanel

1. Πηγαίνετε στο https://autoanosis.com:2083/
2. Login με τα cPanel credentials

#### Step 2: Open Cron Jobs

1. Scroll down στο **"Advanced"** section
2. Πατήστε **"Cron Jobs"**

#### Step 3: Add Cron Job

1. Στο "Add New Cron Job" section:

**Minute**: `*`  
**Hour**: `*`  
**Day**: `*`  
**Month**: `*`  
**Weekday**: `*`

**Command**:
```bash
wget -q -O - https://autoanosis.com/wp-cron.php?doing_wp_cron >/dev/null 2>&1
```

2. Πατήστε **"Add New Cron Job"**

#### Step 4: Verify

Ίδια διαδικασία με Option 1.

---

### Option 3: SSH (Advanced)

Αν έχετε SSH access:

#### Step 1: SSH Login

```bash
ssh username@autoanosis.com
```

#### Step 2: Edit Crontab

```bash
crontab -e
```

#### Step 3: Add Line

```bash
* * * * * curl -s https://autoanosis.com/wp-cron.php?doing_wp_cron >/dev/null 2>&1
```

#### Step 4: Save and Exit

- Πατήστε `Esc`
- Γράψτε `:wq`
- Πατήστε `Enter`

#### Step 5: Verify

```bash
crontab -l
```

Πρέπει να δείτε τη γραμμή που προσθέσατε.

---

## 🔍 Troubleshooting

### Πρόβλημα: Δεν βλέπω το Cron Jobs menu

**Λύση:**
- Ελέγξτε αν έχετε access στο Site Tools
- Αν όχι, χρησιμοποιήστε cPanel (Option 2)
- Ή ζητήστε από το SiteGround support να το ενεργοποιήσει

### Πρόβλημα: Cron Job δεν τρέχει

**Ελέγξτε:**

1. **Command σωστό;**
   ```bash
   curl -s https://autoanosis.com/wp-cron.php?doing_wp_cron >/dev/null 2>&1
   ```
   Προσοχή: Το URL πρέπει να είναι το δικό σας!

2. **Interval σωστό;**
   - Πρέπει να είναι "Every 1 minute"

3. **Enabled;**
   - Πρέπει να είναι ✅ Yes

4. **Test manually:**
   ```bash
   curl -I https://autoanosis.com/wp-cron.php
   ```
   Πρέπει να επιστρέψει `200 OK`

### Πρόβλημα: "Command not found: curl"

**Λύση:**
Χρησιμοποιήστε `wget` αντί για `curl`:

```bash
wget -q -O - https://autoanosis.com/wp-cron.php?doing_wp_cron >/dev/null 2>&1
```

### Πρόβλημα: "Permission denied"

**Λύση:**
Ελέγξτε ότι το wp-cron.php είναι readable:

```bash
chmod 644 /path/to/wordpress/wp-cron.php
```

---

## 📊 Verification

### Method 1: WordPress Diagnostics

1. Πηγαίνετε στο Medical Memory → Diagnostics
2. Ελέγξτε "Cron Health (Last 24 Hours)"
3. Πρέπει να δείτε:
   - **check_medications**: > 1440 runs (24 hours × 60 minutes)
   - **Successful Runs**: > 95%
   - **Last Run**: < 2 minutes ago

### Method 2: Cron Log

```bash
# SSH into server
tail -f /var/log/cron.log | grep wp-cron
```

Πρέπει να βλέπετε νέες γραμμές κάθε λεπτό.

### Method 3: Database

```sql
-- Check cron_log table
SELECT * FROM tkc_mm_cron_log 
ORDER BY started_at DESC 
LIMIT 10;
```

Πρέπει να βλέπετε νέες εγγραφές κάθε λεπτό.

---

## ⚙️ Advanced Configuration

### Disable WordPress Built-in Cron

Αφού ρυθμίσετε το server cron, μπορείτε να απενεργοποιήσετε το WP-Cron:

1. Επεξεργαστείτε το `wp-config.php`
2. Προσθέστε πριν το `/* That's all, stop editing! */`:

```php
define('DISABLE_WP_CRON', true);
```

**Πλεονεκτήματα:**
- Καλύτερη performance (δεν τρέχει σε κάθε page load)
- Πιο αξιόπιστο (server cron μόνο)

**Μειονεκτήματα:**
- Αν χαλάσει το server cron, τίποτα δεν θα τρέχει

**Συνιστώ:** Αφήστε το WP-Cron enabled για backup.

### Change Interval

Αν θέλετε να αλλάξετε το interval (π.χ. κάθε 2 λεπτά):

**SiteGround Site Tools:**
- Interval: `Every 2 minutes`

**cPanel:**
```bash
*/2 * * * * curl -s https://autoanosis.com/wp-cron.php?doing_wp_cron >/dev/null 2>&1
```

**Προσοχή:** Για ιατρικές ειδοποιήσεις, συνιστώ **1 minute**.

---

## 📝 Cron Syntax Reference

```
* * * * * command
│ │ │ │ │
│ │ │ │ └─── Day of week (0-7, 0 and 7 = Sunday)
│ │ │ └───── Month (1-12)
│ │ └─────── Day of month (1-31)
│ └───────── Hour (0-23)
└─────────── Minute (0-59)
```

**Examples:**

```bash
# Every minute
* * * * * command

# Every 5 minutes
*/5 * * * * command

# Every hour at minute 0
0 * * * * command

# Every day at 2 AM
0 2 * * * command

# Every Monday at 3 AM
0 3 * * 1 command
```

---

## 🎉 Success!

Αν όλα πήγαν καλά, θα δείτε:

1. **SiteGround Site Tools → Cron Jobs**
   - Medical Memory Notifications: ✅ Active
   - Last Run: < 1 minute ago

2. **WordPress → Medical Memory → Diagnostics**
   - Cron Health: ✅ All jobs active
   - Last Run: < 2 minutes ago
   - Successful Runs: > 0

3. **Test Notification**
   - Προσθέστε φάρμακο με ώρα +5 λεπτά
   - Λάβετε notification εντός 1-2 λεπτών

---

## 📞 Support

Αν χρειαστείτε βοήθεια:

1. **SiteGround Support**
   - Live Chat: https://my.siteground.com/support
   - Πείτε τους: "I need to set up a cron job to run every minute"

2. **WordPress Diagnostics**
   - Medical Memory → Diagnostics
   - Screenshot και στείλτε μου

---

**Version**: 12.0.0  
**Date**: 2026-02-23  
**Estimated Time**: 5-10 minutes
