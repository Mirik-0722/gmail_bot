import asyncio
from types import SimpleNamespace

from cryptography.fernet import Fernet

from gmail_bot import bot, mail_client
from gmail_bot.mail_client import Attachment, IncomingMail
from gmail_bot.storage import Storage

CHAT = 42


class FakeBot:
    def __init__(self, fail_documents=False):
        self.texts: list[str] = []
        self.documents: list[str] = []
        self.fail_documents = fail_documents

    async def send_message(self, chat_id, text, **kwargs):
        self.texts.append(text)

    async def send_document(self, chat_id, document, filename, **kwargs):
        if self.fail_documents:
            raise RuntimeError("telegram xato")
        self.documents.append(filename)

    async def send_chat_action(self, *args, **kwargs):
        pass


def make_context(tmp_path, fake_bot, last_uid=0):
    st = Storage(str(tmp_path / "t.db"), Fernet.generate_key().decode())
    st.save(CHAT, "me@gmail.com", "pw", last_uid)
    bot_data = {"storage": st, "auth_failed": set(), "albums": {}, "delivery_failures": {}}
    return SimpleNamespace(bot=fake_bot, bot_data=bot_data), st


def test_subject_for():
    assert bot._subject_for("Salom\nikkinchi", None) == "Telegram: Salom"
    assert bot._subject_for("x" * 70, None) == "Telegram: " + "x" * 60 + "…"
    assert bot._subject_for("", "a.pdf") == "Telegram: a.pdf"
    assert bot._subject_for("", None) == "Telegram xabar"


def test_poll_delivers_and_advances_uid(tmp_path, monkeypatch):
    fb = FakeBot()
    ctx, st = make_context(tmp_path, fb)
    mails = [IncomingMail(3, "Mavzu", "matn", [Attachment("f.txt", b"1")])]
    monkeypatch.setattr(mail_client, "fetch_new", lambda *a: (mails, 4))

    asyncio.run(bot.poll_gmail(ctx))

    assert fb.texts == ["📧 Mavzu\n\nmatn"]
    assert fb.documents == ["f.txt"]
    assert st.get(CHAT).last_uid == 4


def test_long_body_is_split(tmp_path, monkeypatch):
    fb = FakeBot()
    ctx, _ = make_context(tmp_path, fb)
    monkeypatch.setattr(
        mail_client, "fetch_new", lambda *a: ([IncomingMail(1, "S", "a" * 9000)], 1)
    )
    asyncio.run(bot.poll_gmail(ctx))
    assert len(fb.texts) == 3
    assert all(len(t) <= bot.TG_TEXT_LIMIT for t in fb.texts)


def test_failed_mail_is_retried_then_skipped(tmp_path, monkeypatch):
    fb = FakeBot(fail_documents=True)
    ctx, st = make_context(tmp_path, fb)
    bad = IncomingMail(5, "Buzilgan", "", [Attachment("f.bin", b"1")])
    good = IncomingMail(6, "Yaxshi", "", [])

    def fetch(address, pw, after_uid):
        mails = [m for m in (bad, good) if m.uid > after_uid]
        return mails, 6

    monkeypatch.setattr(mail_client, "fetch_new", fetch)

    for _ in range(bot.MAX_DELIVERY_ATTEMPTS - 1):
        asyncio.run(bot.poll_gmail(ctx))
        assert st.get(CHAT).last_uid == 4  # shu xat qayta uriniladi
    assert "📧 Yaxshi" not in fb.texts

    asyncio.run(bot.poll_gmail(ctx))  # oxirgi urinish — o'tkazib yuboriladi
    assert st.get(CHAT).last_uid == 6
    assert "📧 Yaxshi" in fb.texts
    assert any("yetkazib bo'lmadi" in t for t in fb.texts)
    assert ctx.bot_data["delivery_failures"] == {}


def test_auth_error_notifies_once(tmp_path, monkeypatch):
    fb = FakeBot()
    ctx, _ = make_context(tmp_path, fb)

    def fail(*a):
        raise mail_client.MailAuthError("bad")

    monkeypatch.setattr(mail_client, "fetch_new", fail)
    asyncio.run(bot.poll_gmail(ctx))
    asyncio.run(bot.poll_gmail(ctx))
    assert len(fb.texts) == 1


class FakeTgFile:
    def __init__(self, data):
        self.data = data

    async def download_as_bytearray(self):
        return bytearray(self.data)


class FakeMedia:
    def __init__(self, uid, data=b"img", size=3):
        self.file_unique_id = uid
        self.file_size = size
        self._data = data

    async def get_file(self):
        return FakeTgFile(self._data)


class FakeMessage:
    def __init__(self, message_id, caption=None, photo=None, text=None):
        self.message_id = message_id
        self.text = text
        self.caption = caption
        self.photo = [photo] if photo else []
        self.document = self.video = self.audio = self.voice = None
        self.video_note = self.animation = None
        self.replies: list[str] = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


def test_album_is_sent_as_one_mail(tmp_path, monkeypatch):
    ctx, _ = make_context(tmp_path, FakeBot())
    sent = []
    monkeypatch.setattr(mail_client, "send_to_self", lambda *a: sent.append(a))
    msgs = [
        FakeMessage(11, photo=FakeMedia("b")),
        FakeMessage(10, caption="Sayohat", photo=FakeMedia("a")),
    ]

    asyncio.run(bot._send_messages(ctx, CHAT, sorted(msgs, key=lambda m: m.message_id)))

    [(address, pw, subject, body, attachments)] = sent
    assert subject == "Telegram: Sayohat"
    assert body == "Sayohat"
    assert [a.filename for a in attachments] == ["photo_a.jpg", "photo_b.jpg"]
    assert msgs[1].replies == ["📨 Gmail'ga yuborildi"]


def test_too_big_file_is_reported(tmp_path, monkeypatch):
    ctx, _ = make_context(tmp_path, FakeBot())
    sent = []
    monkeypatch.setattr(mail_client, "send_to_self", lambda *a: sent.append(a))
    msg = FakeMessage(1, photo=FakeMedia("big", size=bot.TG_DOWNLOAD_LIMIT + 1))

    asyncio.run(bot._send_messages(ctx, CHAT, [msg]))

    assert sent == []
    assert "20 MB" in msg.replies[0]


class FakeJobQueue:
    def __init__(self):
        self.jobs = []

    def run_once(self, callback, when, data=None, chat_id=None):
        self.jobs.append((callback, data))


def test_album_parts_are_buffered_and_flushed(tmp_path, monkeypatch):
    ctx, _ = make_context(tmp_path, FakeBot())
    ctx.job_queue = FakeJobQueue()
    sent = []
    monkeypatch.setattr(mail_client, "send_to_self", lambda *a: sent.append(a))

    for i, uid in ((2, "b"), (1, "a")):
        msg = FakeMessage(i, photo=FakeMedia(uid))
        msg.media_group_id = "G"
        update = SimpleNamespace(effective_message=msg, effective_chat=SimpleNamespace(id=CHAT))
        asyncio.run(bot.forward_to_gmail(update, ctx))

    assert sent == []
    [(callback, data)] = ctx.job_queue.jobs  # albom uchun faqat bitta job
    ctx.job = SimpleNamespace(data=data)
    asyncio.run(callback(ctx))

    [(_, _, subject, _, attachments)] = sent
    assert subject == "Telegram: 2 ta fayl"
    assert [a.filename for a in attachments] == ["photo_a.jpg", "photo_b.jpg"]
    assert ctx.bot_data["albums"] == {}
