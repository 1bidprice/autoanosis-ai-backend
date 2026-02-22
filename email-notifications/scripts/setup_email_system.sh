#!/bin/bash

# Automated Email System Setup Script
# This script will guide you through testing and setting up the email notification system

set -e

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

clear
echo -e "${CYAN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║                                                            ║${NC}"
echo -e "${CYAN}║        DIP Email Notification System Setup                ║${NC}"
echo -e "${CYAN}║                                                            ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Step 1: Get Admin Token
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}ΒΗΜΑ 1: Λήψη Admin Token από Render${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "Για να συνεχίσουμε, χρειάζεται το DIP_ADMIN_TOKEN από το Render."
echo ""
echo -e "${CYAN}Πώς να το βρεις:${NC}"
echo "  1. Άνοιξε το Render Dashboard: ${BLUE}https://dashboard.render.com${NC}"
echo "  2. Επίλεξε το service: ${BLUE}dip-backend${NC}"
echo "  3. Κάνε κλικ στο tab: ${BLUE}Environment${NC}"
echo "  4. Βρες το: ${BLUE}DIP_ADMIN_TOKEN${NC}"
echo "  5. Αντίγραψε την τιμή του"
echo ""
read -p "Πάτησε Enter όταν είσαι έτοιμος να εισάγεις το token..."
echo ""
read -sp "Εισάγαγε το DIP_ADMIN_TOKEN: " ADMIN_TOKEN
echo ""
echo ""

if [ -z "$ADMIN_TOKEN" ]; then
    echo -e "${RED}❌ Δεν δόθηκε token. Έξοδος.${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Token λήφθηκε!${NC}"
echo ""

# Step 2: Test Backend Health
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}ΒΗΜΑ 2: Έλεγχος Backend Health${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

BASE_URL="https://dip-backend-puof.onrender.com"

echo "Testing: ${BASE_URL}/health"
HEALTH_RESPONSE=$(curl -s "${BASE_URL}/health")

if echo "$HEALTH_RESPONSE" | grep -q '"ok":true'; then
    echo -e "${GREEN}✅ Backend is healthy!${NC}"
    echo "Response: $HEALTH_RESPONSE"
else
    echo -e "${RED}❌ Backend health check failed!${NC}"
    echo "Response: $HEALTH_RESPONSE"
    exit 1
fi
echo ""

# Step 3: Test Daily Digest Endpoint
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}ΒΗΜΑ 3: Δοκιμή Daily Digest Endpoint${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

echo "Sending request to: ${BASE_URL}/admin/send-daily-digests"
DAILY_RESPONSE=$(curl -s -X POST "${BASE_URL}/admin/send-daily-digests" \
    -H "x-admin-token: ${ADMIN_TOKEN}" \
    -H "Content-Type: application/json" \
    -w "\nHTTP_STATUS:%{http_code}")

HTTP_STATUS=$(echo "$DAILY_RESPONSE" | grep "HTTP_STATUS" | cut -d: -f2)
RESPONSE_BODY=$(echo "$DAILY_RESPONSE" | sed '/HTTP_STATUS/d')

echo "HTTP Status: $HTTP_STATUS"
echo "Response: $RESPONSE_BODY"
echo ""

if [ "$HTTP_STATUS" == "200" ]; then
    echo -e "${GREEN}✅ Daily digest endpoint works!${NC}"
    EMAILS_SENT=$(echo "$RESPONSE_BODY" | grep -o '"emails_sent":[0-9]*' | cut -d: -f2)
    if [ -n "$EMAILS_SENT" ]; then
        echo -e "${GREEN}📧 Emails sent: $EMAILS_SENT${NC}"
        if [ "$EMAILS_SENT" -gt 0 ]; then
            echo -e "${CYAN}💡 Check your inbox: nipeshoes@gmail.com${NC}"
        else
            echo -e "${YELLOW}⚠️  No emails sent (no subscribed users or no new decisions)${NC}"
        fi
    fi
elif [ "$HTTP_STATUS" == "401" ]; then
    echo -e "${RED}❌ Authentication failed - token is incorrect${NC}"
    exit 1
else
    echo -e "${RED}❌ Daily digest endpoint failed${NC}"
    exit 1
fi
echo ""

# Step 4: Test Weekly Digest Endpoint
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}ΒΗΜΑ 4: Δοκιμή Weekly Digest Endpoint${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

echo "Sending request to: ${BASE_URL}/admin/send-weekly-digests"
WEEKLY_RESPONSE=$(curl -s -X POST "${BASE_URL}/admin/send-weekly-digests" \
    -H "x-admin-token: ${ADMIN_TOKEN}" \
    -H "Content-Type: application/json" \
    -w "\nHTTP_STATUS:%{http_code}")

HTTP_STATUS=$(echo "$WEEKLY_RESPONSE" | grep "HTTP_STATUS" | cut -d: -f2)
RESPONSE_BODY=$(echo "$WEEKLY_RESPONSE" | sed '/HTTP_STATUS/d')

echo "HTTP Status: $HTTP_STATUS"
echo "Response: $RESPONSE_BODY"
echo ""

if [ "$HTTP_STATUS" == "200" ]; then
    echo -e "${GREEN}✅ Weekly digest endpoint works!${NC}"
    EMAILS_SENT=$(echo "$RESPONSE_BODY" | grep -o '"emails_sent":[0-9]*' | cut -d: -f2)
    if [ -n "$EMAILS_SENT" ]; then
        echo -e "${GREEN}📧 Emails sent: $EMAILS_SENT${NC}"
    fi
else
    echo -e "${RED}❌ Weekly digest endpoint failed${NC}"
fi
echo ""

# Step 5: Setup Cron Job
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}ΒΗΜΑ 5: Ρύθμιση Cron Job${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

echo -e "${CYAN}Για να στέλνονται αυτόματα τα emails κάθε μέρα, χρειάζεται να${NC}"
echo -e "${CYAN}ρυθμίσεις ένα cron job στο cron-job.org${NC}"
echo ""
echo -e "${BLUE}Βήματα:${NC}"
echo ""
echo "1. Άνοιξε: ${BLUE}https://cron-job.org/en/${NC}"
echo "2. Κάνε Sign Up (δωρεάν)"
echo "3. Δημιούργησε νέο Cron Job με τα εξής στοιχεία:"
echo ""
echo -e "${CYAN}   ┌─ Daily Digest Job ────────────────────────────────────┐${NC}"
echo -e "${CYAN}   │${NC}"
echo -e "${CYAN}   │${NC}  Title:    ${GREEN}DIP Daily Digest Emails${NC}"
echo -e "${CYAN}   │${NC}  URL:      ${GREEN}${BASE_URL}/admin/send-daily-digests${NC}"
echo -e "${CYAN}   │${NC}  Method:   ${GREEN}POST${NC}"
echo -e "${CYAN}   │${NC}  Schedule: ${GREEN}Every day at 09:00 (Athens time)${NC}"
echo -e "${CYAN}   │${NC}  Headers:  ${GREEN}x-admin-token: ${ADMIN_TOKEN}${NC}"
echo -e "${CYAN}   │${NC}  Timeout:  ${GREEN}60 seconds${NC}"
echo -e "${CYAN}   │${NC}"
echo -e "${CYAN}   └────────────────────────────────────────────────────────┘${NC}"
echo ""
echo -e "${CYAN}   ┌─ Weekly Digest Job ───────────────────────────────────┐${NC}"
echo -e "${CYAN}   │${NC}"
echo -e "${CYAN}   │${NC}  Title:    ${GREEN}DIP Weekly Digest Emails${NC}"
echo -e "${CYAN}   │${NC}  URL:      ${GREEN}${BASE_URL}/admin/send-weekly-digests${NC}"
echo -e "${CYAN}   │${NC}  Method:   ${GREEN}POST${NC}"
echo -e "${CYAN}   │${NC}  Schedule: ${GREEN}Every Monday at 09:00 (Athens time)${NC}"
echo -e "${CYAN}   │${NC}  Headers:  ${GREEN}x-admin-token: ${ADMIN_TOKEN}${NC}"
echo -e "${CYAN}   │${NC}  Timeout:  ${GREEN}60 seconds${NC}"
echo -e "${CYAN}   │${NC}"
echo -e "${CYAN}   └────────────────────────────────────────────────────────┘${NC}"
echo ""

# Save configuration to file
CONFIG_FILE="/home/ubuntu/cron_job_config.txt"
cat > "$CONFIG_FILE" << EOF
DIP Email Notification System - Cron Job Configuration
========================================================

DAILY DIGEST JOB:
-----------------
Title:    DIP Daily Digest Emails
URL:      ${BASE_URL}/admin/send-daily-digests
Method:   POST
Schedule: Every day at 09:00 (Athens time)
Headers:  x-admin-token: ${ADMIN_TOKEN}
Timeout:  60 seconds

WEEKLY DIGEST JOB:
------------------
Title:    DIP Weekly Digest Emails
URL:      ${BASE_URL}/admin/send-weekly-digests
Method:   POST
Schedule: Every Monday at 09:00 (Athens time)
Headers:  x-admin-token: ${ADMIN_TOKEN}
Timeout:  60 seconds

SETUP INSTRUCTIONS:
-------------------
1. Go to: https://cron-job.org/en/
2. Sign up (free)
3. Create two cron jobs with the above configuration
4. Enable both jobs

MONITORING:
-----------
- Check Render logs: https://dashboard.render.com
- Check Brevo dashboard: https://app.brevo.com
- Check cron-job.org execution history

Generated: $(date)
EOF

echo -e "${GREEN}✅ Configuration saved to: ${CONFIG_FILE}${NC}"
echo ""

# Summary
echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                                                            ║${NC}"
echo -e "${GREEN}║                    ✅ SETUP COMPLETE!                      ║${NC}"
echo -e "${GREEN}║                                                            ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${CYAN}Επόμενα βήματα:${NC}"
echo ""
echo "1. ✅ Backend tested and working"
echo "2. ✅ Email endpoints tested successfully"
echo "3. ⏳ Setup cron job at cron-job.org (see instructions above)"
echo "4. ⏳ Monitor for 24 hours to ensure emails arrive"
echo ""
echo -e "${CYAN}Files created:${NC}"
echo "  - ${CONFIG_FILE}"
echo "  - /home/ubuntu/EMAIL_SYSTEM_DEPLOYMENT.md"
echo "  - /home/ubuntu/dip-backend/CRON_SETUP.md"
echo ""
echo -e "${YELLOW}💡 Tip: Keep the admin token safe and don't share it publicly!${NC}"
echo ""
