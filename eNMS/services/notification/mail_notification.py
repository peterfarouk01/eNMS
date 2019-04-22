from flask_mail import Message
from sqlalchemy import Column, ForeignKey, Integer, String

from eNMS.framework import get_one
from eNMS.modules import mail_client
from eNMS.models import register_class
from eNMS.models.automation import Service


class MailNotificationService(Service, metaclass=register_class):

    __tablename__ = "MailNotificationService"

    id = Column(Integer, ForeignKey("Service.id"), primary_key=True)
    title = Column(String(255))
    sender = Column(String(255))
    recipients = Column(String(255))
    body = Column(String(255))
    body_textarea = True

    __mapper_args__ = {"polymorphic_identity": "MailNotificationService"}

    def job(self, _) -> dict:
        parameters = get_one("Parameters")
        if self.recipients:
            recipients = self.recipients.split(",")
        else:
            recipients = parameters.mail_sender.split(",")
        sender = self.sender or parameters.mail_sender
        self.logs.append(f"Sending mail {self.title} to {sender}")
        message = Message(
            self.title, sender=sender, recipients=recipients, body=self.body
        )
        mail_client.send(message)
        return {"success": True, "result": str(message)}