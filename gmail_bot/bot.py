"""Telegram <-> Gmail ko'prigi.

* Telegram botga yuborilgan matn/fayl -> sozlamadagi Gmail'ga (o'zidan o'ziga) xat bo'lib boradi.
* Gmail'da o'zingizga yuborgan xatingiz -> Telegram botga keladi.
"""
import asyncio
import logging
import re

from telegram import Message, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    TypeHandler,
    filters,
)

from . import mail_client
from .config import Config, load_config
from .mail_client import Attachment, MailAuthError
from .storage import Storage

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("gmail_bot")

ASK_EMAIL, ASK_PASSWORD = range(2)

TG_TEXT_LIMIT = 4000
TG_DOWNLOAD_LIMIT = 20 * 1024 * 1024  # Bot API getFile limiti
TG_UPLOAD_LIMIT = 50 * 1024 * 1024  # Bot API sendDocument limiti
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

HELP_TEXT = (
    "Salom! Bu bot Telegram va Gmail'ni bog'laydi:\n\n"
    "• Botga matn yoki fayl yuborsangiz — u Gmail'ingizda xat bo'lib ko'rinadi.\n"
    "• Gmail'dan o'zingizga (o'z manzilingizga) xat yuborsangiz — u shu yerga keladi.\n\n"
    "Buyruqlar:\n"
    "/settings — Gmail manzili va App Password'ni kiritish\n"
    "/status — joriy sozlama\n"
    "/disconnect — Gmail'ni uzish\n"
    "/cancel — sozlashni bekor qilish"
)

PASSWORD_HELP = (
    "Endi Gmail uchun <b>App Password</b> (ilova paroli) yuboring.\n\n"
    "Oddiy Gmail parol ishlamaydi. App Password olish:\n"
    "1. Google hisobingizda 2 bosqichli tekshiruvni yoqing\n"
    "2. https://myaccount.google.com/apppasswords ga kiring\n"
    "3. Yangi parol yarating va 16 belgili kodni shu yerga yuboring\n\n"
    "Xavfsizlik uchun parolli xabaringiz chatdan o'chiriladi."
)


def storage(context: ContextTypes.DEFAULT_TYPE) -> Storage:
    return context.bot_data["storage"]


# --------------------------------------------------------------------------- #
# Kirish nazorati
# --------------------------------------------------------------------------- #
async def access_guard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config: Config = context.bot_data["config"]
    user = update.effective_user
    if config.allowed_users and (user is None or user.id not in config.allowed_users):
        if update.effective_message:
            await update.effective_message.reply_text("Sizga bu botdan foydalanishga ruxsat yo'q.")
        raise ApplicationHandlerStop


# --------------------------------------------------------------------------- #
# Buyruqlar
# --------------------------------------------------------------------------- #
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    s = storage(context).get(update.effective_chat.id)
    if s is None:
        await update.message.reply_text("Gmail ulanmagan. /settings orqali sozlang.")
    else:
        await update.message.reply_text(f"Ulangan Gmail: {s.email}")


async def disconnect(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    storage(context).delete(update.effective_chat.id)
    context.bot_data["auth_failed"].discard(update.effective_chat.id)
    await update.message.reply_text("Gmail uzildi. Qayta ulash uchun /settings.")


# --------------------------------------------------------------------------- #
# /settings suhbati
# --------------------------------------------------------------------------- #
async def settings_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Gmail manzilingizni yuboring (masalan: ism@gmail.com):")
    return ASK_EMAIL


async def settings_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    address = update.message.text.strip()
    if not EMAIL_RE.match(address):
        await update.message.reply_text("Bu email manzilga o'xshamaydi. Qayta yuboring:")
        return ASK_EMAIL
    context.user_data["pending_email"] = address
    await update.message.reply_html(PASSWORD_HELP, disable_web_page_preview=True)
    return ASK_PASSWORD


async def settings_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    app_password = update.message.text.replace(" ", "").strip()
    address = context.user_data.get("pending_email")
    chat_id = update.effective_chat.id

    try:
        await update.message.delete()
    except Exception:
        log.warning("Parolli xabarni o'chirib bo'lmadi (chat %s)", chat_id)

    wait = await context.bot.send_message(chat_id, "Tekshirilmoqda...")
    try:
        last_uid = await asyncio.to_thread(mail_client.check_login, address, app_password)
    except MailAuthError:
        await wait.edit_text(
            "Kirib bo'lmadi: email yoki App Password noto'g'ri.\n"
            "Gmail sozlamalarida IMAP yoqilganini ham tekshiring. Qayta App Password yuboring "
            "yoki /cancel."
        )
        return ASK_PASSWORD
    except Exception as e:
        log.exception("Gmail'ga ulanishda xato")
        await wait.edit_text(f"Gmail'ga ulanib bo'lmadi: {e}\nQayta urinib ko'ring yoki /cancel.")
        return ASK_PASSWORD

    # Eski xatlar botga yog'ilib kelmasligi uchun hozirgi eng oxirgi UID'dan boshlaymiz.
    storage(context).save(chat_id, address, app_password, last_uid)
    context.bot_data["auth_failed"].discard(chat_id)
    context.user_data.pop("pending_email", None)
    await wait.edit_text(
        f"✅ Gmail ulandi: {address}\n\n"
        "Endi botga matn yoki fayl yuboring — u Gmail'ingizga boradi.\n"
        "Gmail'dan o'zingizga yuborgan xatlar esa shu yerga keladi."
    )
    return ConversationHandler.END


async def settings_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("pending_email", None)
    await update.message.reply_text("Bekor qilindi.")
    return ConversationHandler.END


# --------------------------------------------------------------------------- #
# Telegram -> Gmail
# --------------------------------------------------------------------------- #
def _file_of(message: Message) -> tuple[object, str] | None:
    """Xabardagi fayl obyekti va fayl nomini qaytaradi."""
    if message.document:
        d = message.document
        return d, d.file_name or f"document_{d.file_unique_id}"
    if message.photo:
        p = message.photo[-1]  # eng katta o'lcham
        return p, f"photo_{p.file_unique_id}.jpg"
    if message.video:
        v = message.video
        return v, v.file_name or f"video_{v.file_unique_id}.mp4"
    if message.audio:
        a = message.audio
        return a, a.file_name or f"audio_{a.file_unique_id}.mp3"
    if message.voice:
        return message.voice, f"voice_{message.voice.file_unique_id}.ogg"
    if message.video_note:
        return message.video_note, f"video_note_{message.video_note.file_unique_id}.mp4"
    if message.animation:
        a = message.animation
        return a, a.file_name or f"animation_{a.file_unique_id}.mp4"
    return None


def _subject_for(text: str, filename: str | None) -> str:
    if text:
        first_line = text.strip().splitlines()[0]
        return "Telegram: " + (first_line[:60] + "…" if len(first_line) > 60 else first_line)
    if filename:
        return f"Telegram: {filename}"
    return "Telegram xabar"


async def forward_to_gmail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    settings = storage(context).get(update.effective_chat.id)
    if settings is None:
        await message.reply_text("Avval Gmail'ni ulang: /settings")
        return

    text = message.text or message.caption or ""
    attachments: list[Attachment] = []
    filename = None

    file_info = _file_of(message)
    if file_info:
        tg_file, filename = file_info
        size = getattr(tg_file, "file_size", None) or 0
        if size > TG_DOWNLOAD_LIMIT:
            await message.reply_text(
                "Fayl juda katta: Telegram botlari 20 MB dan katta faylni yuklab ololmaydi."
            )
            return
        await context.bot.send_chat_action(message.chat_id, ChatAction.UPLOAD_DOCUMENT)
        f = await tg_file.get_file()
        data = await f.download_as_bytearray()
        attachments.append(Attachment(filename=filename, content=bytes(data)))

    if not text and not attachments:
        await message.reply_text("Bu turdagi xabarni yuborib bo'lmaydi. Matn yoki fayl yuboring.")
        return

    try:
        await asyncio.to_thread(
            mail_client.send_to_self,
            settings.email,
            settings.app_password,
            _subject_for(text, filename),
            text,
            attachments,
        )
    except MailAuthError:
        await message.reply_text("Gmail'ga kirib bo'lmadi. App Password'ni yangilang: /settings")
        return
    except Exception as e:
        log.exception("Xat yuborishda xato")
        await message.reply_text(f"Xat yuborilmadi: {e}")
        return

    await message.reply_text("📨 Gmail'ga yuborildi", reply_to_message_id=message.message_id)


# --------------------------------------------------------------------------- #
# Gmail -> Telegram (davriy tekshiruv)
# --------------------------------------------------------------------------- #
def _chunks(text: str, size: int = TG_TEXT_LIMIT):
    for i in range(0, len(text), size):
        yield text[i : i + size]


async def _deliver(context: ContextTypes.DEFAULT_TYPE, chat_id: int, mail) -> None:
    header = f"📧 {mail.subject}" if mail.subject else "📧 (mavzusiz)"
    text = f"{header}\n\n{mail.body}" if mail.body else header
    for part in _chunks(text):
        await context.bot.send_message(chat_id, part)
    for att in mail.attachments:
        if len(att.content) > TG_UPLOAD_LIMIT:
            await context.bot.send_message(
                chat_id, f"⚠️ {att.filename} juda katta (50 MB dan ortiq), Telegram'ga yuborilmadi."
            )
            continue
        await context.bot.send_document(chat_id, document=att.content, filename=att.filename)


async def _poll_user(context: ContextTypes.DEFAULT_TYPE, settings) -> None:
    st = storage(context)
    auth_failed: set[int] = context.bot_data["auth_failed"]
    try:
        mails, max_uid = await asyncio.to_thread(
            mail_client.fetch_new, settings.email, settings.app_password, settings.last_uid
        )
    except MailAuthError:
        if settings.chat_id not in auth_failed:
            auth_failed.add(settings.chat_id)
            await context.bot.send_message(
                settings.chat_id,
                "⚠️ Gmail'ga kirib bo'lmadi. App Password o'zgargan bo'lishi mumkin: /settings",
            )
        return
    except Exception:
        log.exception("Gmail tekshiruvida xato (chat %s)", settings.chat_id)
        return

    auth_failed.discard(settings.chat_id)
    for mail in mails:
        try:
            await _deliver(context, settings.chat_id, mail)
        except Exception:
            log.exception("Xatni Telegram'ga yetkazishda xato (uid %s)", mail.uid)
            # Yetkazilgan joygacha saqlaymiz, qolganini keyingi safar qayta uriniladi.
            st.update_last_uid(settings.chat_id, mail.uid - 1)
            return
    if max_uid > settings.last_uid:
        st.update_last_uid(settings.chat_id, max_uid)


async def poll_gmail(context: ContextTypes.DEFAULT_TYPE) -> None:
    users = storage(context).all()
    await asyncio.gather(*(_poll_user(context, u) for u in users))


# --------------------------------------------------------------------------- #
def build_app(config: Config) -> Application:
    app = Application.builder().token(config.bot_token).build()
    app.bot_data["config"] = config
    app.bot_data["storage"] = Storage(config.db_path, config.encryption_key)
    app.bot_data["auth_failed"] = set()

    app.add_handler(TypeHandler(Update, access_guard), group=-1)

    app.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("settings", settings_start)],
            states={
                ASK_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_email)],
                ASK_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_password)],
            },
            fallbacks=[CommandHandler("cancel", settings_cancel)],
        )
    )
    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("disconnect", disconnect))

    content = (
        (filters.TEXT & ~filters.COMMAND)
        | filters.Document.ALL
        | filters.PHOTO
        | filters.VIDEO
        | filters.AUDIO
        | filters.VOICE
        | filters.VIDEO_NOTE
        | filters.ANIMATION
    )
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & content, forward_to_gmail))

    app.job_queue.run_repeating(
        poll_gmail,
        interval=config.poll_interval,
        first=5,
        job_kwargs={"max_instances": 1, "coalesce": True},
    )
    return app


def main() -> None:
    config = load_config()
    app = build_app(config)
    log.info("Bot ishga tushdi")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
