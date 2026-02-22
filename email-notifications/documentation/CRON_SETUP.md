# Cron Job Setup για Email Digests

## Επισκόπηση

Το σύστημα email notifications χρειάζεται ένα external cron service για να στέλνει αυτόματα emails κάθε μέρα, επειδή το Render free tier δεν υποστηρίζει built-in cron jobs.

## API Endpoints

Το backend εκθέτει δύο endpoints για αποστολή digest emails:

### 1. Daily Digests
```
POST https://dip-backend-puof.onrender.com/admin/send-daily-digests
Headers:
  x-admin-token: <DIP_ADMIN_TOKEN>
```

### 2. Weekly Digests
```
POST https://dip-backend-puof.onrender.com/admin/send-weekly-digests
Headers:
  x-admin-token: <DIP_ADMIN_TOKEN>
```

## Ρύθμιση με cron-job.org (RECOMMENDED)

### Βήμα 1: Δημιουργία λογαριασμού
1. Πήγαινε στο https://cron-job.org/en/
2. Κάνε sign up (δωρεάν)
3. Verify το email σου

### Βήμα 2: Δημιουργία Daily Cron Job
1. Κάνε κλικ στο "Create cronjob"
2. **Title**: `DIP Daily Digest Emails`
3. **URL**: `https://dip-backend-puof.onrender.com/admin/send-daily-digests`
4. **Request method**: `POST`
5. **Schedule**: 
   - Type: `Every day`
   - Time: `09:00` (Athens time - UTC+2)
6. **Headers**: Κάνε κλικ "Add header"
   - Name: `x-admin-token`
   - Value: `<το DIP_ADMIN_TOKEN από το Render environment variables>`
7. **Timeout**: `60 seconds`
8. **Enabled**: ✅ Yes
9. Κάνε κλικ "Create cronjob"

### Βήμα 3: Δημιουργία Weekly Cron Job
1. Κάνε κλικ στο "Create cronjob"
2. **Title**: `DIP Weekly Digest Emails`
3. **URL**: `https://dip-backend-puof.onrender.com/admin/send-weekly-digests`
4. **Request method**: `POST`
5. **Schedule**: 
   - Type: `Every week`
   - Day: `Monday`
   - Time: `09:00` (Athens time - UTC+2)
6. **Headers**: Κάνε κλικ "Add header"
   - Name: `x-admin-token`
   - Value: `<το DIP_ADMIN_TOKEN από το Render environment variables>`
7. **Timeout**: `60 seconds`
8. **Enabled**: ✅ Yes
9. Κάνε κλικ "Create cronjob"

## Εναλλακτικές Λύσεις

### EasyCron (https://www.easycron.com/)
- Free plan: 20 cron jobs
- Setup παρόμοιο με cron-job.org

### GitHub Actions (Advanced)
Μπορείς να χρησιμοποιήσεις GitHub Actions για να καλείς το API:

```yaml
# .github/workflows/daily-digest.yml
name: Send Daily Digest Emails
on:
  schedule:
    - cron: '0 7 * * *'  # 09:00 Athens time (UTC+2)
jobs:
  send-digest:
    runs-on: ubuntu-latest
    steps:
      - name: Send daily digest
        run: |
          curl -X POST https://dip-backend-puof.onrender.com/admin/send-daily-digests \
            -H "x-admin-token: ${{ secrets.DIP_ADMIN_TOKEN }}"
```

## Testing

Για να δοκιμάσεις αν δουλεύει:

```bash
# Test daily digest
curl -X POST https://dip-backend-puof.onrender.com/admin/send-daily-digests \
  -H "x-admin-token: YOUR_ADMIN_TOKEN"

# Test weekly digest
curl -X POST https://dip-backend-puof.onrender.com/admin/send-weekly-digests \
  -H "x-admin-token: YOUR_ADMIN_TOKEN"
```

## Monitoring

Μπορείς να παρακολουθείς τα logs στο Render Dashboard:
1. Πήγαινε στο https://dashboard.render.com
2. Επίλεξε το `dip-backend` service
3. Κάνε κλικ στο "Logs" tab
4. Ψάξε για μηνύματα όπως:
   - `📧 Found X new decisions for daily digest`
   - `👥 Found X users subscribed to daily digest`
   - `✅ Sent X daily digest emails`

## Troubleshooting

### Τα emails δεν στέλνονται
1. Έλεγξε ότι το `BREVO_API_KEY` είναι σωστό στο Render environment variables
2. Έλεγξε ότι υπάρχουν users με `email_enabled: true` στο database
3. Έλεγξε ότι υπάρχουν νέες αποφάσεις στο database
4. Δες τα logs στο Render για errors

### Το cron job δεν τρέχει
1. Έλεγξε ότι το `x-admin-token` header είναι σωστό
2. Έλεγξε ότι το Render service είναι running (όχι sleeping)
3. Δοκίμασε να καλέσεις το endpoint manually με curl

### Το Render service είναι sleeping
Το free tier του Render κάνει sleep το service μετά από 15 λεπτά inactivity. Το cron job θα το ξυπνήσει αυτόματα, αλλά η πρώτη κλήση μπορεί να πάρει 30-60 δευτερόλεπτα.

**Λύση**: Upgrade σε paid plan ($7/month) για να μην κάνει sleep.
