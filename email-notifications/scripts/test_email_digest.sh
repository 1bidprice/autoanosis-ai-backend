#!/bin/bash

# Test Email Digest Functionality
# This script tests the email digest endpoints

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "================================================"
echo "DIP Email Digest Testing Script"
echo "================================================"
echo ""

# Check if ADMIN_TOKEN is provided
if [ -z "$1" ]; then
    echo -e "${RED}❌ Error: Admin token not provided${NC}"
    echo "Usage: ./test_email_digest.sh YOUR_ADMIN_TOKEN"
    echo ""
    echo "You can find the admin token in Render dashboard:"
    echo "  1. Go to https://dashboard.render.com"
    echo "  2. Select 'dip-backend' service"
    echo "  3. Go to 'Environment' tab"
    echo "  4. Find DIP_ADMIN_TOKEN value"
    exit 1
fi

ADMIN_TOKEN="$1"
BASE_URL="https://dip-backend-puof.onrender.com"

echo -e "${YELLOW}Testing backend health...${NC}"
HEALTH_RESPONSE=$(curl -s "${BASE_URL}/health")
echo "Response: $HEALTH_RESPONSE"
echo ""

if echo "$HEALTH_RESPONSE" | grep -q '"ok":true'; then
    echo -e "${GREEN}✅ Backend is healthy${NC}"
else
    echo -e "${RED}❌ Backend health check failed${NC}"
    exit 1
fi

echo ""
echo "================================================"
echo -e "${YELLOW}Testing Daily Digest Endpoint...${NC}"
echo "================================================"
echo ""

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
    echo -e "${GREEN}✅ Daily digest endpoint responded successfully${NC}"
    
    # Parse the response to show emails sent
    EMAILS_SENT=$(echo "$RESPONSE_BODY" | grep -o '"emails_sent":[0-9]*' | cut -d: -f2)
    if [ -n "$EMAILS_SENT" ]; then
        echo -e "${GREEN}📧 Emails sent: $EMAILS_SENT${NC}"
    fi
elif [ "$HTTP_STATUS" == "401" ]; then
    echo -e "${RED}❌ Authentication failed - check your admin token${NC}"
    exit 1
else
    echo -e "${RED}❌ Daily digest endpoint failed with status $HTTP_STATUS${NC}"
fi

echo ""
echo "================================================"
echo -e "${YELLOW}Testing Weekly Digest Endpoint...${NC}"
echo "================================================"
echo ""

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
    echo -e "${GREEN}✅ Weekly digest endpoint responded successfully${NC}"
    
    # Parse the response to show emails sent
    EMAILS_SENT=$(echo "$RESPONSE_BODY" | grep -o '"emails_sent":[0-9]*' | cut -d: -f2)
    if [ -n "$EMAILS_SENT" ]; then
        echo -e "${GREEN}📧 Emails sent: $EMAILS_SENT${NC}"
    fi
elif [ "$HTTP_STATUS" == "401" ]; then
    echo -e "${RED}❌ Authentication failed - check your admin token${NC}"
    exit 1
else
    echo -e "${RED}❌ Weekly digest endpoint failed with status $HTTP_STATUS${NC}"
fi

echo ""
echo "================================================"
echo -e "${GREEN}Testing Complete!${NC}"
echo "================================================"
echo ""
echo "Next steps:"
echo "1. Check your email (nipeshoes@gmail.com) for digest emails"
echo "2. If no emails received, check Render logs for errors"
echo "3. Set up cron job using instructions in CRON_SETUP.md"
echo ""
