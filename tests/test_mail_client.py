import pytest

from gmail_bot import mail_client
from gmail_bot.mail_client import Attachment, MailAuthError

from .conftest import ADDRESS, PASSWORD, make_mail, parse


def test_send_to_self_builds_marked_mail_with_attachment(fake_mail):
    smtp, _ = fake_mail
    mail_client.send_to_self(ADDRESS, PASSWORD, "Mavzu", "Salom", [Attachment("a.pdf", b"%PDF")])

    msg = parse(smtp.sent[0])
    assert msg["From"] == msg["To"] == ADDRESS
    assert msg["Subject"] == "Mavzu"
    assert msg[mail_client.BOT_HEADER] == "1"
    assert msg.get_body(("plain",)).get_content().strip() == "Salom"
    [att] = list(msg.iter_attachments())
    assert att.get_filename() == "a.pdf"
    assert att.get_content_type() == "application/pdf"
    assert att.get_payload(decode=True) == b"%PDF"


def test_send_to_self_bad_password(fake_mail):
    with pytest.raises(MailAuthError):
        mail_client.send_to_self(ADDRESS, "wrong", "s", "b")


def test_check_login_returns_max_uid(fake_mail):
    _, imap = fake_mail
    imap.mailbox = {3: make_mail(), 11: make_mail()}
    assert mail_client.check_login(ADDRESS, PASSWORD) == 11
    with pytest.raises(MailAuthError):
        mail_client.check_login(ADDRESS, "wrong")


def test_check_login_empty_inbox(fake_mail):
    assert mail_client.check_login(ADDRESS, PASSWORD) == 0


def test_fetch_new_skips_old_and_bot_mails(fake_mail):
    smtp, imap = fake_mail
    mail_client.send_to_self(ADDRESS, PASSWORD, "botdan", "x")
    imap.mailbox = {
        5: make_mail("eski"),
        7: smtp.sent[0],
        8: make_mail("yangi", "oddiy matn", attachments=[("n.txt", b"xyz")]),
    }

    mails, max_uid = mail_client.fetch_new(ADDRESS, PASSWORD, after_uid=5)

    assert max_uid == 8
    assert [m.uid for m in mails] == [8]
    assert mails[0].subject == "yangi"
    assert mails[0].body == "oddiy matn"
    assert [(a.filename, a.content) for a in mails[0].attachments] == [("n.txt", b"xyz")]
    assert f'FROM "{ADDRESS}" TO "{ADDRESS}"' in imap.searches[-1]


def test_fetch_new_nothing_new(fake_mail):
    _, imap = fake_mail
    imap.mailbox = {5: make_mail()}
    assert mail_client.fetch_new(ADDRESS, PASSWORD, after_uid=5) == ([], 5)


def test_html_only_mail_is_converted_to_text(fake_mail):
    from email.message import EmailMessage

    _, imap = fake_mail
    msg = EmailMessage()
    msg["Subject"] = "H"
    msg.set_content("<style>p{}</style><b>Qalin</b><br>x &amp; y", subtype="html")
    imap.mailbox = {1: msg.as_bytes()}

    [mail], _ = mail_client.fetch_new(ADDRESS, PASSWORD, after_uid=0)
    assert mail.body == "Qalin\nx & y"
