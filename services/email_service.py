# import os
# import logging
# from sendgrid import SendGridAPIClient
# from sendgrid.helpers.mail import Mail

# logger = logging.getLogger(__name__)
# logging.basicConfig(level=logging.INFO)


# class EmailService:
#     """
#     Centralized email utility for TeamFlow (Option B – organization-based structure).
#     Handles sending user invitations and other transactional emails via SendGrid.
#     """

#     def __init__(self):
#         self.sendgrid_api_key = os.getenv("SENDGRID_API_KEY")
#         self.sender_email = os.getenv("MAIL_FROM")

#         self.enabled = bool(self.sendgrid_api_key and self.sender_email)
#         if not self.enabled:
#             logger.warning("📧 Email service not configured. Missing SENDGRID_API_KEY or MAIL_FROM.")
#         else:
#             logger.info(f"📧 Email service configured and ready. Sender: {self.sender_email}")

#     # ============================================================
#     # ✅ Send Invitation Email
#     # ============================================================
#     async def send_invitation_email(
#         self,
#         to_email: str,
#         invitation_link: str,
#         role: str,
#         org_name: str,
#         invited_by: str = "Admin"
#     ) -> bool:
#         """
#         Sends an invitation email with a valid link for the invited user.
#         The link must already include a valid URL-safe token.

#         Args:
#             to_email (str): Recipient email address
#             invitation_link (str): Direct activation link (already valid URL)
#             role (str): Role assigned to the invitee (e.g. Member, Admin)
#             org_name (str): Organization name (for context)
#             invited_by (str): Name of the inviter
#         """

#         if not self.enabled:
#             # Development fallback (no SendGrid setup)
#             logger.info(f"📨 [Mock Email] To: {to_email}")
#             logger.info(f"Link: {invitation_link}")
#             logger.info(f"Role: {role} | Organization: {org_name}")
#             return True

#         subject = f"🎉 You're invited to join {org_name} on TeamFlow as {role.title()}!"

#         html_content = f"""
#         <div style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
#             <h2>👋 Hello!</h2>
#             <p><strong>{invited_by}</strong> has invited you to join the organization 
#             <strong>{org_name}</strong> on <b>TeamFlow</b> as 
#             <strong>{role.title()}</strong>.</p>

#             <p>Click below to accept your invitation:</p>

#             <p style="text-align: center; margin: 20px 0;">
#                 <a href="{invitation_link}" style="
#                     background-color: #4F46E5;
#                     color: white;
#                     padding: 12px 28px;
#                     text-decoration: none;
#                     border-radius: 6px;
#                     font-weight: bold;
#                     display: inline-block;
#                 ">✅ Accept Invitation</a>
#             </p>

#             <p>If the button doesn’t work, copy and paste this link into your browser:</p>
#             <p style="word-break: break-all; color: #555;">{invitation_link}</p>

#             <p><small>This invitation will expire in 7 days.</small></p>
#             <hr style="border:none; border-top:1px solid #eee; margin: 24px 0;">
#             <p>Best regards,<br><strong>The TeamFlow Team</strong></p>
#         </div>
#         """

#         try:
#             message = Mail(
#                 from_email=self.sender_email,
#                 to_emails=to_email,
#                 subject=subject,
#                 html_content=html_content,
#             )

#             sg = SendGridAPIClient(self.sendgrid_api_key)
#             response = sg.send(message)

#             logger.info(f"✅ Invitation email sent to {to_email}. Status: {response.status_code}")
#             return True

#         except Exception as e:
#             logger.error(f"❌ Failed to send invitation email to {to_email}: {e}")
#             return False


# # ============================================================
# # ✅ Global instance for app-wide import
# # ============================================================
# email_service = EmailService()


















import os
import logging
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class EmailService:
    """
    Centralized email utility for TeamFlow.
    Handles sending user invitations and other transactional emails via SendGrid.
    """

    def __init__(self):
        self.sendgrid_api_key = os.getenv("SENDGRID_API_KEY")
        self.sender_email = os.getenv("MAIL_FROM")

        self.enabled = bool(self.sendgrid_api_key and self.sender_email)
        if not self.enabled:
            logger.warning("📧 Email service not configured. Missing SENDGRID_API_KEY or MAIL_FROM.")
        else:
            logger.info(f"📧 Email service configured and ready. Sender: {self.sender_email}")

    # ============================================================
    # ✅ Send Invitation Email (synchronous for BackgroundTasks)
    # ============================================================
    def send_invitation_email(
        self,
        to_email: str,
        invitation_link: str,
        role: str,
        org_name: str,
        invited_by: str = "Admin"
    ) -> bool:
        """Synchronous email send (works with FastAPI BackgroundTasks)."""

        if not self.enabled:
            # Development fallback (no SendGrid setup)
            logger.info(f"📨 [Mock Email] To: {to_email}")
            logger.info(f"Link: {invitation_link}")
            logger.info(f"Role: {role} | Organization: {org_name}")
            return True

        subject = f"🎉 You're invited to join {org_name} on TeamFlow as {role.title()}!"

        html_content = f"""
        <div style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <h2>👋 Hello!</h2>
            <p><strong>{invited_by}</strong> has invited you to join the organization 
            <strong>{org_name}</strong> on <b>TeamFlow</b> as 
            <strong>{role.title()}</strong>.</p>

            <p>Click below to accept your invitation:</p>

            <p style="text-align: center; margin: 20px 0;">
                <a href="{invitation_link}" style="
                    background-color: #4F46E5;
                    color: white;
                    padding: 12px 28px;
                    text-decoration: none;
                    border-radius: 6px;
                    font-weight: bold;
                    display: inline-block;
                ">✅ Accept Invitation</a>
            </p>

            <p>If the button doesn’t work, copy and paste this link into your browser:</p>
            <p style="word-break: break-all; color: #555;">{invitation_link}</p>

            <p><small>This invitation will expire in 7 days.</small></p>
            <hr style="border:none; border-top:1px solid #eee; margin: 24px 0;">
            <p>Best regards,<br><strong>The TeamFlow Team</strong></p>
        </div>
        """

        try:
            message = Mail(
                from_email=self.sender_email,
                to_emails=to_email,
                subject=subject,
                html_content=html_content,
            )
            sg = SendGridAPIClient(self.sendgrid_api_key)
            response = sg.send(message)
            logger.info(f"✅ Invitation email sent to {to_email}. Status: {response.status_code}")
            return True
        except Exception as e:
            logger.exception("❌ Failed to send invitation email to %s: %s", to_email, e)
            return False


# ============================================================
# ✅ Global instance for app-wide import
# ============================================================
email_service = EmailService()
