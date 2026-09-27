"""Gmail bilan ishlash: SMTP orqali yuborish, IMAP orqali o'qish.

Barcha funksiyalar bloklovchi (sinxron) — bot ularni asyncio.to_thread orqali chaqiradi.
"""
import email
import html
import imaplib
import mimetypes
import re
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.policy import default as default_policy
from email.utils import formatdate, make_msgid

IMAP_HOST = "imap.gmail.com"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465

# Bot yuborgan xatlarga qo'yiladigan belgi — ular qaytib botga kelmasligi uchun.
BOT_HEADER = "X-Telegram-Gmail-Bot"


@dataclass
class Attachment:
    filename: str
    content: bytes


@dataclass
class IncomingMail:
    uid: int
    subject: str
    body: str
    attachments: list[Attachment] = field(default_factory=list)


class MailAuthError(Exception):
    pass


def check_login(address: str, app_password: str) -> int:
    """Login ma'lumotlarini tekshiradi va INBOX'dagi eng katta UID'ni qaytaradi."""
    imap = _imap_login(address, app_password)
    try:
        imap.select("INBOX", readonly=True)
        typ, data = imap.uid("SEARCH", None, "ALL")
        uids = [int(x) for x in data[0].split()] if typ == "OK" and data[0] else []
        return max(uids, default=0)
    finally:
        _imap_logout(imap)


def send_to_self(
    address: str,
    app_password: str,
    subject: str,
    body: str,
    attachments: list[Attachment] | None = None,
) -> None:
    msg = EmailMessage()
    msg["From"] = address
    msg["To"] = address
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="telegram.bot")
    msg[BOT_HEADER] = "1"
    msg.set_content(body or "")
    for att in attachments or []:
        ctype, _ = mimetypes.guess_type(att.filename)
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        msg.add_attachment(
            att.content, maintype=maintype, subtype=subtype, filename=att.filename
        )

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=60) as smtp:
            smtp.login(address, app_password)
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise MailAuthError(str(e)) from e


def fetch_new(
    address: str, app_password: str, after_uid: int
) -> tuple[list[IncomingMail], int]:
    """INBOX'dan after_uid dan keyingi, o'zidan o'ziga yuborilgan xatlarni oladi.

    (yangi_xatlar, eng_katta_ko'rilgan_uid) qaytaradi. Bot o'zi yuborgan xatlar
    (BOT_HEADER bilan) ro'yxatga kirmaydi, lekin UID hisobiga olinadi.
    """
    imap = _imap_login(address, app_password)
    try:
        imap.select("INBOX", readonly=True)
        criteria = f'(UID {after_uid + 1}:* FROM "{address}" TO "{address}")'
        typ, data = imap.uid("SEARCH", None, criteria)
        if typ != "OK" or not data[0]:
            return [], after_uid
        # "N:*" har doim kamida oxirgi xatni qaytaradi, shuning uchun filtrlaymiz.
        uids = sorted(u for u in (int(x) for x in data[0].split()) if u > after_uid)

        result: list[IncomingMail] = []
        max_uid = after_uid
        for uid in uids:
            max_uid = max(max_uid, uid)
            typ, msg_data = imap.uid("FETCH", str(uid), "(BODY.PEEK[])")
            if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                continue
            msg = email.message_from_bytes(msg_data[0][1], policy=default_policy)
            if msg.get(BOT_HEADER):
                continue
            result.append(_parse(uid, msg))
        return result, max_uid
    finally:
        _imap_logout(imap)


def _parse(uid: int, msg: EmailMessage) -> IncomingMail:
    body = ""
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is not None:
        body = part.get_content()
        if part.get_content_type() == "text/html":
            body = _html_to_text(body)

    attachments = []
    for att in msg.iter_attachments():
        payload = att.get_payload(decode=True)
        if payload is None:
            continue
        filename = att.get_filename() or "attachment"
        attachments.append(Attachment(filename=filename, content=payload))

    return IncomingMail(
        uid=uid,
        subject=str(msg.get("Subject", "") or ""),
        body=body.strip(),
        attachments=attachments,
    )


def _html_to_text(text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", "", text)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text)


def _imap_login(address: str, app_password: str) -> imaplib.IMAP4_SSL:
    imap = imaplib.IMAP4_SSL(IMAP_HOST, timeout=60)
    try:
        imap.login(address, app_password)
    except imaplib.IMAP4.error as e:
        _imap_logout(imap)
        raise MailAuthError(str(e)) from e
    return imap


def _imap_logout(imap: imaplib.IMAP4_SSL) -> None:
    try:
        imap.logout()
    except Exception:
        pass
