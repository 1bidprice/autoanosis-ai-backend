# 🎯 Email Notification System - Final Setup

## ✅ Τι Έχει Ολοκληρωθεί

1. **Backend Email Service** ✅
   - Email service με Brevo API
   - Daily/Weekly digest functionality
   - Content filtering (υγεία, συντάξεις, ΚΕΠΑ, κοινωνική πρόνοια)
   - API endpoints: `/admin/send-daily-digests` και `/admin/send-weekly-digests`
   - Professional HTML email template
   - **Deployed on Render** και τρέχει

2. **GitHub Actions Workflows** ✅
   - `daily-digest.yml` - Τρέχει κάθε μέρα στις 09:00
   - `weekly-digest.yml` - Τρέχει κάθε Δευτέρα στις 09:00
   - Αρχεία δημιουργημένα στο `/home/ubuntu/dip-backend/.github/workflows/`

---

## 🚀 Τελικά Βήματα (5 λεπτά)

### ΒΗΜΑ 1: Πάρε το Admin Token από Render

1. Άνοιξε: https://dashboard.render.com
2. Κάνε κλικ στο **dip-backend** service
3. Πήγαινε στο **Environment** tab (αριστερά)
4. Βρες το **DIP_ADMIN_TOKEN**
5. Κάνε κλικ στο μάτι (👁️) για να το δεις
6. **Αντίγραψέ το** (κράτα το σε notepad)

---

### ΒΗΜΑ 2: Πρόσθεσε το Secret στο GitHub

1. Άνοιξε: https://github.com/1bidprice/dip-backend/settings/secrets/actions
2. Κάνε κλικ **New repository secret**
3. Name: `DIP_ADMIN_TOKEN`
4. Value: **Κόλλησε το token από το Βήμα 1**
5. Κάνε κλικ **Add secret**

---

### ΒΗΜΑ 3: Ανέβασε τα GitHub Actions Workflows

Τρέξε αυτές τις εντολές στο terminal:

```bash
cd /home/ubuntu/dip-backend
git add .github/workflows/*.yml
git commit -m "Add automated email digest workflows"
git push origin main
```

**ΣΗΜΕΙΩΣΗ:** Αν το push αποτύχει λόγω permissions, κάνε το manually:

1. Άνοιξε: https://github.com/1bidprice/dip-backend
2. Κάνε κλικ **Add file** → **Create new file**
3. Όνομα αρχείου: `.github/workflows/daily-digest.yml`
4. Αντίγραψε το περιεχόμενο από `/home/ubuntu/dip-backend/.github/workflows/daily-digest.yml`
5. Κάνε **Commit**
6. Επανάλαβε για `weekly-digest.yml`

---

### ΒΗΜΑ 4: Δοκιμή (Optional αλλά Recommended)

Δοκίμασε αν δουλεύει το email system:

```bash
curl -X POST https://dip-backend-puof.onrender.com/admin/send-daily-digests \
  -H "x-admin-token: YOUR_ADMIN_TOKEN_HERE" \
  -H "Content-Type: application/json"
```

**Αναμενόμενο αποτέλεσμα:**
```json
{"success":true,"emails_sent":1}
```

Έλεγξε το email σου (nipeshoes@gmail.com) για το digest email!

---

### ΒΗΜΑ 5: Ενεργοποίηση GitHub Actions (Αυτόματο)

Μόλις κάνεις push τα workflows, το GitHub θα τα ενεργοποιήσει αυτόματα.

Μπορείς να τα δεις εδώ:
https://github.com/1bidprice/dip-backend/actions

---

## 📧 Τι Θα Συμβαίνει από Εδώ και Πέρα

### Αυτόματα Emails
- **Κάθε μέρα στις 09:00** → Daily digest email
- **Κάθε Δευτέρα στις 09:00** → Weekly digest email

### Περιεχόμενο Emails
- Λίστα νέων κυβερνητικών αποφάσεων
- Φιλτραρισμένες: ΜΟΝΟ υγεία, συντάξεις, ΚΕΠΑ, κοινωνική πρόνοια
- Χωρίς διοικητικές μαλακίες (μισθοδοσίες, προμήθειες, κλπ)
- Clickable links στο Διαύγεια
- Professional Autoanosis branding

### Manual Trigger (Αν Χρειαστεί)
Μπορείς να τρέξεις manually τα workflows από:
https://github.com/1bidprice/dip-backend/actions

Κάνε κλικ στο workflow → **Run workflow**

---

## 🎨 Email Template Preview

Το email θα έχει:
- **Header:** Autoanosis branding με logo
- **Title:** "Νέες Κυβερνητικές Αποφάσεις - Ημερήσια Ενημέρωση"
- **Content:** Λίστα αποφάσεων με:
  - Τίτλος απόφασης
  - Ημερομηνία έκδοσης
  - Αριθμός πρωτοκόλλου
  - Link στο Διαύγεια
- **CTA Button:** "Δείτε Περισσότερες Αποφάσεις"
- **Footer:** Unsubscribe link + contact info

---

## 🔧 Troubleshooting

### Δεν έφτασε email
- Έλεγξε το spam folder
- Έλεγξε ότι το DIP_ADMIN_TOKEN είναι σωστό στα GitHub secrets
- Δες τα logs στο Render: https://dashboard.render.com → dip-backend → Logs

### GitHub Actions δεν τρέχουν
- Έλεγξε ότι τα workflows είναι στο main branch
- Έλεγξε ότι το DIP_ADMIN_TOKEN secret υπάρχει
- Δες τα logs: https://github.com/1bidprice/dip-backend/actions

### 401 Unauthorized error
- Το admin token είναι λάθος
- Πάρε το ξανά από το Render και ενημέρωσε το GitHub secret

---

## 📁 Αρχεία που Δημιουργήθηκαν

```
/home/ubuntu/dip-backend/
├── .github/workflows/
│   ├── daily-digest.yml      # Daily email automation
│   └── weekly-digest.yml     # Weekly email automation
├── dip/app/
│   ├── email_service.py      # Email service με Brevo API
│   └── main.py               # API endpoints
└── dip/email_template.html   # Professional email template
```

---

## ✅ Checklist

- [ ] Πήρα το DIP_ADMIN_TOKEN από Render
- [ ] Πρόσθεσα το secret στο GitHub
- [ ] Ανέβασα τα GitHub Actions workflows
- [ ] Δοκίμασα το email endpoint
- [ ] Έλεγξα ότι έφτασε το test email
- [ ] Επιβεβαίωσα ότι τα GitHub Actions είναι ενεργά

---

## 🎉 ΤΕΛΟΣ!

Μόλις ολοκληρώσεις τα 3 βήματα, το email notification system θα είναι **πλήρως αυτοματοποιημένο** και θα τρέχει κάθε μέρα χωρίς να χρειάζεται να κάνεις τίποτα!

**Καλή επιτυχία!** 🚀
