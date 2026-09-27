# Telegram ↔ Gmail bot

* Botga **matn yoki fayl** yuborsangiz → u sozlamada ko'rsatilgan **Gmail**'ga xat bo'lib boradi (o'zingizdan o'zingizga).
* Gmail'dan **o'zingizga** (o'z manzilingizga) xat yuborsangiz → u **Telegram bot**ga keladi (matn + fayllar).

Bot yuborgan xatlarga maxsus `X-Telegram-Gmail-Bot` sarlavhasi qo'yiladi, shuning uchun ular qaytib botga kelmaydi.

## O'rnatish

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

`.env` faylini to'ldiring:

* `TELEGRAM_BOT_TOKEN` — [@BotFather](https://t.me/BotFather) dan olingan token
* `ENCRYPTION_KEY` — App Password'larni shifrlash kaliti:
  ```bash
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```
* `POLL_INTERVAL` — Gmail necha sekundda bir tekshirilsin (standart 30)
* `ALLOWED_USERS` — (ixtiyoriy) ruxsat berilgan Telegram user ID'lar

Ishga tushirish:

```bash
python -m gmail_bot
```

## Docker Compose bilan ishga tushirish

`.env` faylini yuqoridagidek to'ldiring, keyin:

```bash
docker compose up -d --build     # ishga tushirish
docker compose logs -f           # loglarni ko'rish
docker compose down              # to'xtatish
```

Baza (`gmail_bot.db`) `bot-data` volume'ida saqlanadi, shuning uchun konteyner qayta
yaratilsa yoki yangilansa ham sozlamalar yo'qolmaydi. Bot server qayta ishga tushganda
avtomatik ko'tariladi (`restart: unless-stopped`).

Kod o'zgargandan keyin yangilash:

```bash
git pull && docker compose up -d --build
```

> ⚠️ `docker compose down -v` volume'ni ham o'chiradi — barcha sozlamalar yo'qoladi.
> `ENCRYPTION_KEY`ni ham o'zgartirmang, aks holda saqlangan parollarni o'qib bo'lmaydi.

## Gmail tomonini tayyorlash

1. Google hisobida **2 bosqichli tekshiruv**ni yoqing.
2. https://myaccount.google.com/apppasswords da **App Password** yarating (16 belgi).
3. Gmail → Sozlamalar → *Forwarding and POP/IMAP* → **IMAP** yoqilganini tekshiring.

## Botdan foydalanish

| Buyruq | Vazifasi |
|---|---|
| `/settings` | Gmail manzili va App Password'ni kiritish (parolli xabar chatdan o'chiriladi) |
| `/status` | Qaysi Gmail ulanganini ko'rsatadi |
| `/disconnect` | Gmail'ni uzish |
| `/cancel` | Sozlashni bekor qilish |

Qo'llab-quvvatlanadigan xabarlar: matn, hujjat, rasm, video, audio, ovozli xabar, dumaloq video, GIF.
Albom (bir nechta rasm/fayl birga) yuborilsa — hammasi **bitta xat** bo'lib boradi.

## Cheklovlar

* Telegram botlari 20 MB dan katta faylni yuklab ololmaydi, 50 MB dan kattasini yubora olmaydi.
* Gmail'dan faqat **o'zingizdan o'zingizga** (From va To — sizning manzilingiz) yuborilgan xatlar botga keladi.
* Ulashda eski xatlar yuborilmaydi — faqat ulangandan keyin kelganlari.
* Gmail'dagi xatni Telegram'ga yetkazib bo'lmasa, bot 3 marta urinadi, keyin ogohlantirib o'tkazib yuboradi (keyingi xatlar to'silib qolmaydi).

## Testlar

```bash
pip install -r requirements-dev.txt
python -m pytest
```
