import email
import imaplib
import smtplib
from email.message import EmailMessage

import pytest

ADDRESS = "me@gmail.com"
PASSWORD = "app-pw"


class FakeSMTP:
    sent: list[bytes] = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        if password != PASSWORD:
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    def send_message(self, msg):
        FakeSMTP.sent.append(msg.as_bytes())


class FakeIMAP:
    mailbox: dict[int, bytes] = {}
    searches: list[str] = []

    def __init__(self, *args, **kwargs):
        pass

    def login(self, user, password):
        if password != PASSWORD:
            raise imaplib.IMAP4.error("bad credentials")

    def select(self, *args, **kwargs):
        return "OK", [b"1"]

    def uid(self, command, *args):
        if command == "SEARCH":
            criteria = args[-1]
            FakeIMAP.searches.append(criteria)
            uids = sorted(self.mailbox)
            if criteria != "ALL":
                # Haqiqiy IMAP kabi: "N:*" oxirgi xatni har doim qaytaradi.
                start = int(criteria.split()[1].split(":")[0])
                uids = [u for u in uids if u >= start] or uids[-1:]
            return "OK", [" ".join(map(str, uids)).encode()]
        uid = int(args[0])
        return "OK", [(b"header", self.mailbox[uid]), b")"]

    def logout(self):
        pass


@pytest.fixture
def fake_mail(monkeypatch):
    FakeSMTP.sent = []
    FakeIMAP.mailbox = {}
    FakeIMAP.searches = []
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(imaplib, "IMAP4_SSL", FakeIMAP)
    return FakeSMTP, FakeIMAP


def make_mail(subject="Salom", body="matn", html=None, attachments=()):
    msg = EmailMessage()
    msg["From"] = ADDRESS
    msg["To"] = ADDRESS
    msg["Subject"] = subject
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    for name, data in attachments:
        msg.add_attachment(data, maintype="application", subtype="octet-stream", filename=name)
    return msg.as_bytes()


def parse(raw: bytes):
    return email.message_from_bytes(raw, policy=email.policy.default)

