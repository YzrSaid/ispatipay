# Ispatipay

A CLI tool to download Spotify music through a Telegram bot. Paste any Spotify track, album, or playlist link and the audio files are downloaded directly to your machine.

---

## How It Works

1. You paste a Spotify link into the CLI.
2. The tool forwards it to a configured Telegram bot (e.g. [SpotiDown](https://t.me/spotifydownloaderbot) or similar).
3. The bot replies with audio files.
4. Ispatipay detects the files, clicks **GET ALL** if available, and downloads everything automatically with a live progress bar.

---

## Requirements

- Python 3.9+
- A [Telegram account](https://telegram.org/)
- Your own Telegram API credentials (free — see setup below)

---

## Installation

**1. Clone the repository**

```bash
git clone https://github.com/YzrSaid/ispatipay.git
cd ispatipay
```

**2. Create and activate a virtual environment**

```bash
python -m venv venv

# Linux / macOS
source venv/bin/activate

# Windows
venv\Scripts\activate
```

**3. Install dependencies**

```bash
pip install -r requirements.txt
```

---

## Configuration

### Step 1 — Get your Telegram API credentials

1. Go to [https://my.telegram.org/apps](https://my.telegram.org/apps) and log in with your phone number.
2. Click **Create new application**.
3. Fill in any app name and short name (e.g. `ispatipay`).
4. Copy your **API ID** (a number) and **API Hash** (a long hex string).

> These credentials are tied to your personal Telegram account. Keep them private and never commit them to version control.

### Step 2 — Find the bot username

Choose a Telegram bot that accepts Spotify links and sends back audio files. Copy its username (e.g. `@spotifydownloaderbot`).

### Step 3 — Create the `.env` file

Create a file named `.env` in the project root:

```env
API_ID=12345678
API_HASH=your_api_hash_here
BOT_USERNAME=@yourbotusername
```

| Variable       | Description                                      |
|----------------|--------------------------------------------------|
| `API_ID`       | Integer ID from my.telegram.org/apps             |
| `API_HASH`     | Hash string from my.telegram.org/apps            |
| `BOT_USERNAME` | Telegram username of the bot (with `@` prefix)   |

> The `.env` file is listed in `.gitignore` and will not be committed.

---

## Usage

```bash
python main.py
```

On first run, Telegram will ask you to verify your phone number and (if enabled) your 2FA password. A session file (`telegram_session.session`) is created locally so you only authenticate once.

**Workflow inside the CLI:**

1. Select **[1] Start Downloader** from the menu.
2. Paste a Spotify link (track, album, or playlist).
3. Wait — the tool handles button clicks and downloads automatically.
4. When complete, choose whether to download another link or return to the menu.
5. Press `q` at any time to go back to the menu.

Downloaded files are saved to:

```
~/Downloads/telegram_downloads/
```

---

## Project Structure

```
ispatipay/
├── main.py          # Entry point — CLI menu and banner
├── downloader.py    # Core downloader logic (Telegram client + progress)
├── requirements.txt
├── .env             # Your credentials (never commit this)
└── .gitignore
```

---

## .gitignore

Make sure your `.gitignore` includes:

```
.env
*.session
*.session-journal
venv/
__pycache__/
```

---

## License

MIT — see [LICENSE](LICENSE) for details.

---

## Author

**Mohammad Aldrin Said** — [github.com/YzrSaid](https://github.com/YzrSaid)
