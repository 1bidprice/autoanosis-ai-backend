"""
Email Service using Brevo API
"""
import httpx
import os
from typing import Dict, Any, List
from jinja2 import Template
from datetime import datetime, timedelta
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession


class EmailService:
    def __init__(self):
        self.api_key = os.getenv("BREVO_API_KEY")
        self.from_email = os.getenv("SMTP_FROM_EMAIL", "onboarding@resend.dev")
        self.from_name = os.getenv("SMTP_FROM_NAME", "DIP Platform")
        self.api_url = "https://api.brevo.com/v3/smtp/email"
        
        # Load email template
        template_path = os.path.join(os.path.dirname(__file__), "..", "email_template.html")
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                self.digest_template = Template(f.read())
        except FileNotFoundError:
            print(f"⚠️  Email template not found at {template_path}")
            self.digest_template = None
        
    async def send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        template_data: Dict[str, Any] = None
    ) -> bool:
        """
        Send email using Brevo API
        
        Args:
            to_email: Recipient email address
            subject: Email subject
            html_content: HTML content (can include Jinja2 template variables)
            template_data: Data to render in the template
            
        Returns:
            bool: True if email sent successfully, False otherwise
        """
        try:
            # Render template if template_data provided
            if template_data:
                template = Template(html_content)
                html_content = template.render(**template_data)
            
            # Prepare request payload
            payload = {
                "sender": {
                    "name": self.from_name,
                    "email": self.from_email
                },
                "to": [
                    {
                        "email": to_email
                    }
                ],
                "subject": subject,
                "htmlContent": html_content
            }
            
            # Send request to Brevo API
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.api_url,
                    json=payload,
                    headers={
                        "api-key": self.api_key,
                        "Content-Type": "application/json"
                    },
                    timeout=30.0
                )
                
                if response.status_code in [200, 201]:
                    print(f"✅ Email sent successfully to {to_email}")
                    return True
                else:
                    error_msg = response.text
                    print(f"❌ Failed to send email to {to_email}: {response.status_code} - {error_msg}")
                    return False
                    
        except Exception as e:
            print(f"❌ Exception sending email to {to_email}: {str(e)}")
            return False


    async def send_templated_email(
        self,
        to_email: str,
        template_subject: str = None,
        template_body: str = None,
        context: Dict[str, Any] = None,
        # Legacy parameters for compatibility
        subject: str = None,
        html_content: str = None,
        template_data: Dict[str, Any] = None
    ) -> bool:
        """Send templated email with flexible parameter support"""
        # Use new-style parameters if provided, otherwise fall back to legacy
        final_subject = template_subject or subject or "Notification"
        final_body = template_body or html_content or ""
        final_data = context or template_data or {}
        
        return await self.send_email(to_email, final_subject, final_body, final_data)


    def render_digest_email(self, decisions: List[Dict], frequency: str) -> str:
        """
        Render digest email HTML from template
        
        Args:
            decisions: List of decision dictionaries
            frequency: Email frequency ('daily' or 'weekly')
            
        Returns:
            Rendered HTML string
        """
        if not self.digest_template:
            return "<p>Email template not available</p>"
        
        if frequency == "daily":
            greeting = "Καλημέρα!"
            intro_text = "Εδώ είναι οι νέες κυβερνητικές αποφάσεις για σήμερα που αφορούν την υγεία, τις συντάξεις και την κοινωνική πρόνοια:"
        else:  # weekly
            greeting = "Καλημέρα!"
            intro_text = "Εδώ είναι οι νέες κυβερνητικές αποφάσεις της εβδομάδας που αφορούν την υγεία, τις συντάξεις και την κοινωνική πρόνοια:"
        
        # Format decisions for template
        formatted_decisions = []
        for decision in decisions:
            formatted_decisions.append({
                "title": decision.get("subject", "Χωρίς τίτλο"),
                "url": f"https://diavgeia.gov.gr/decision/view/{decision.get('ada', '')}",
                "date": decision.get("issue_date", "")[:10] if decision.get("issue_date") else "",
                "protocol": decision.get("protocol_number", "N/A")
            })
        
        return self.digest_template.render(
            greeting=greeting,
            intro_text=intro_text,
            decisions=formatted_decisions
        )
    
    async def get_new_decisions(self, db: AsyncSession, since_date: datetime) -> List[Dict]:
        """
        Get new decisions from database since a specific date
        
        Args:
            db: Database session
            since_date: Get decisions published after this date
            
        Returns:
            List of decision dictionaries
        """
        from .models import SourceEvent
        
        # Health keywords
        health_keywords = [
            'υγεί', 'νοσοκομεί', 'φάρμακ', 'ιατρ', 'ασθεν', 'θεραπεί', 'ΕΣΥ', 'ΕΟΠΥΥ',
            'κλινικ', 'υγειονομ', 'ιατροφαρμακευτ', 'φαρμακευτ', 'ιατρικ'
        ]
        
        # Pension keywords
        pension_keywords = [
            'σύνταξ', 'συνταξ', 'συνταξιοδοτ', 'συντάξιμ', 'συνταξιούχ',
            'αναπηρικ σύνταξ', 'γηρατικ σύνταξ'
        ]
        
        # KEPA and disability keywords
        kepa_keywords = [
            'ΚΕΠΑ', 'αναπηρ', 'αναπήρ', 'αμεα', 'ΑΜΕΑ', 'αναπηρικ',
            'πιστοποίηση αναπηρίας', 'ποσοστό αναπηρίας'
        ]
        
        # Social welfare keywords
        social_keywords = [
            'κοινωνικ επίδομ', 'επίδομ στέγασης', 'επίδομ παιδιού',
            'προνοιακ επίδομ', 'ευάλωτ', 'στήριξ', 'βοήθημ',
            'κοινωνικ παροχ', 'οικονομικ ενίσχυσ'
        ]
        
        # Exclusion patterns
        exclusion_patterns = [
            'εργοδοτικ εισφορ', 'αμοιβ προσωπικ', 'μισθοδοσί',
            'προμήθει', 'σύμβασ', 'ανάθεσ', 'διαγωνισμ',
            'πρόσληψ', 'διορισμ', 'τοποθέτησ', 'μετάταξ',
            'προσλήψεων', 'διοικητικ πράξ', 'οργανόγραμμ'
        ]
        
        # Combine all inclusion keywords
        all_keywords = health_keywords + pension_keywords + kepa_keywords + social_keywords
        
        # Build OR condition for inclusion
        inclusion_conditions = []
        for keyword in all_keywords:
            inclusion_conditions.append(SourceEvent.title.ilike(f'%{keyword}%'))
            inclusion_conditions.append(SourceEvent.summary.ilike(f'%{keyword}%'))
        
        # Build AND NOT condition for exclusion
        exclusion_conditions = []
        for pattern in exclusion_patterns:
            exclusion_conditions.append(~SourceEvent.title.ilike(f'%{pattern}%'))
            exclusion_conditions.append(~SourceEvent.summary.ilike(f'%{pattern}%'))
        
        # Build query
        query = select(SourceEvent).where(
            and_(
                SourceEvent.published_at >= since_date.isoformat(),
                or_(*inclusion_conditions),
                *exclusion_conditions
            )
        ).order_by(SourceEvent.published_at.desc()).limit(50)
        
        result = await db.execute(query)
        rows = result.scalars().all()
        
        return [
            {
                "ada": row.external_ref,
                "subject": row.title,
                "protocol_number": row.external_ref.split('/')[-1] if '/' in row.external_ref else row.external_ref,
                "issue_date": row.published_at,
                "url": row.url
            }
            for row in rows
        ]
    
    async def get_subscribed_users(self, db: AsyncSession, frequency: str) -> List[Dict]:
        """
        Get users subscribed to email notifications with specific frequency
        
        Args:
            db: Database session
            frequency: Email frequency ('daily', 'weekly', or 'immediate')
            
        Returns:
            List of user dictionaries with email and UUID
        """
        from .notifications import NotificationPreference
        
        # For 'immediate', we don't send digest emails
        if frequency == "immediate":
            return []
        
        query = select(NotificationPreference).where(
            and_(
                NotificationPreference.email_enabled == True,
                NotificationPreference.email_address.isnot(None),
                NotificationPreference.email_address != '',
                NotificationPreference.frequency == frequency
            )
        )
        
        result = await db.execute(query)
        rows = result.scalars().all()
        
        return [
            {
                "external_id": row.external_id,
                "email_address": row.email_address,
                "frequency": row.frequency
            }
            for row in rows
        ]
    
    async def send_digest_emails(self, db: AsyncSession, frequency: str) -> Dict[str, int]:
        """
        Send digest emails to all subscribed users
        
        Args:
            db: Database session
            frequency: Email frequency ('daily' or 'weekly')
            
        Returns:
            Dictionary with counts of sent/failed emails
        """
        # Calculate date range
        if frequency == "daily":
            since_date = datetime.now() - timedelta(days=1)
            subject = "Νέες Κυβερνητικές Αποφάσεις - Ημερήσια Ενημέρωση"
        else:  # weekly
            since_date = datetime.now() - timedelta(days=7)
            subject = "Νέες Κυβερνητικές Αποφάσεις - Εβδομαδιαία Ενημέρωση"
        
        # Get new decisions
        decisions = await self.get_new_decisions(db, since_date)
        
        if not decisions:
            print(f"ℹ️  No new decisions found for {frequency} digest")
            return {"sent": 0, "failed": 0, "skipped": 0}
        
        print(f"📧 Found {len(decisions)} new decisions for {frequency} digest")
        
        # Get subscribed users
        users = await self.get_subscribed_users(db, frequency)
        
        if not users:
            print(f"ℹ️  No users subscribed to {frequency} digest")
            return {"sent": 0, "failed": 0, "skipped": len(decisions)}
        
        print(f"👥 Found {len(users)} users subscribed to {frequency} digest")
        
        # Render email HTML
        html_content = self.render_digest_email(decisions, frequency)
        
        # Send emails
        sent_count = 0
        failed_count = 0
        
        for user in users:
            email = user["email_address"]
            success = await self.send_email(email, subject, html_content)
            
            if success:
                sent_count += 1
            else:
                failed_count += 1
        
        return {
            "sent": sent_count,
            "failed": failed_count,
            "decisions_count": len(decisions)
        }


# Global instance
email_service = EmailService()


# Helper functions for cron jobs
async def send_daily_digests() -> int:
    """
    Send daily digest emails to all subscribed users.
    
    Returns:
        Number of emails sent
    """
    from .db import SessionLocal
    
    async with SessionLocal() as db:
        result = await email_service.send_digest_emails(db, "daily")
        return result["sent"]


async def send_weekly_digests() -> int:
    """
    Send weekly digest emails to all subscribed users.
    
    Returns:
        Number of emails sent
    """
    from .db import SessionLocal
    
    async with SessionLocal() as db:
        result = await email_service.send_digest_emails(db, "weekly")
        return result["sent"]
