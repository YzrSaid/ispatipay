import asyncio
import json
import os
import random
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import readchar
from dotenv import load_dotenv
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from telethon import TelegramClient, events

load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_USERNAME = os.getenv("BOT_USERNAME")
SESSION = "telegram_session"

AUDIO_EXTENSIONS = (".mp3", ".m4a", ".wav", ".flac", ".ogg", ".aac")
DOWNLOAD_TIMEOUT = 180

IS_WINDOWS = sys.platform == "win32"
MPV_IPC_SOCK = r"\\.\pipe\ispatipay_mpv" if IS_WINDOWS else "/tmp/ispatipay_mpv.sock"


def _find_mpv() -> str:
    found = shutil.which("mpv")
    if found:
        return found
    if IS_WINDOWS:
        for p in [
            r"C:\Program Files\MPV Player\mpv.exe",
            r"C:\Program Files\mpv\mpv.exe",
        ]:
            if os.path.isfile(p):
                return p
    raise FileNotFoundError("mpv not found — install it and add to PATH")


MPV_PATH = _find_mpv()

EQ_COLS = 24
EQ_HEIGHT = 6
BAR_WIDTH = 34

console = Console()


class StreamPlayer:
    """One mpv subprocess — audio piped in from Telegram, controlled via IPC."""

    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self._ipc = None            # socket (Linux) or file object (Windows)
        self._ipc_is_pipe = False    # True when using Windows named pipe
        self._pipe_task: asyncio.Task | None = None
        self.is_playing = False
        self.is_paused = False
        self._start_time: float | None = None
        self._offset = 0.0

    # ── Start / Kill ───────────────────────────────────────────────────

    async def start(self, client: TelegramClient, media):
        await self.kill()

        if not IS_WINDOWS:
            try:
                os.unlink(MPV_IPC_SOCK)
            except FileNotFoundError:
                pass

        self.proc = subprocess.Popen(
            [MPV_PATH, "--no-video", "--really-quiet",
             f"--input-ipc-server={MPV_IPC_SOCK}", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Wait up to 1.5 s for mpv to create the IPC socket / named pipe
        self._ipc = None
        self._ipc_is_pipe = False
        for _ in range(30):
            try:
                if IS_WINDOWS:
                    f = open(MPV_IPC_SOCK, "r+b", buffering=0)
                    self._ipc = f
                    self._ipc_is_pipe = True
                else:
                    s = socket.socket(socket.AF_UNIX)
                    s.connect(MPV_IPC_SOCK)
                    self._ipc = s
                break
            except (FileNotFoundError, OSError, ConnectionRefusedError):
                await asyncio.sleep(0.05)

        self.is_playing = True
        self.is_paused = False
        self._start_time = time.time()
        self._offset = 0.0

        # Stream chunks to mpv stdin in the background
        self._pipe_task = asyncio.create_task(self._pipe_chunks(client, media))

    async def _pipe_chunks(self, client: TelegramClient, media):
        loop = asyncio.get_event_loop()
        try:
            async for chunk in client.iter_download(media):
                if self.proc is None or self.proc.stdin is None:
                    break
                try:
                    await loop.run_in_executor(None, self.proc.stdin.write, chunk)
                except (BrokenPipeError, OSError):
                    break
        except asyncio.CancelledError:
            pass
        finally:
            try:
                if self.proc and self.proc.stdin:
                    self.proc.stdin.close()
            except Exception:
                pass

    async def kill(self):
        if self._pipe_task:
            self._pipe_task.cancel()
            try:
                await self._pipe_task
            except (asyncio.CancelledError, Exception):
                pass
            self._pipe_task = None

        if self._ipc:
            try:
                self._ipc.close()
            except Exception:
                pass
            self._ipc = None

        if self.proc:
            try:
                self.proc.kill()
                self.proc.wait(timeout=2)
            except Exception:
                pass
            self.proc = None

        self.is_playing = False
        self.is_paused = False
        self._offset = 0.0
        self._start_time = None

    # ── Controls ───────────────────────────────────────────────────────

    def _ipc_send(self, *args):
        if self._ipc:
            try:
                data = (json.dumps({"command": list(args)}) + "\n").encode()
                if self._ipc_is_pipe:
                    self._ipc.write(data)
                    self._ipc.flush()
                else:
                    self._ipc.sendall(data)
            except Exception:
                pass

    def toggle_pause(self):
        if not self.is_playing:
            return
        if self.is_paused:
            self._start_time = time.time()
            self._ipc_send("set_property", "pause", False)
            self.is_paused = False
        else:
            self._offset += time.time() - (self._start_time or time.time())
            self._ipc_send("set_property", "pause", True)
            self.is_paused = True

    # ── State ──────────────────────────────────────────────────────────

    def get_position(self) -> float:
        if not self.is_playing:
            return 0.0
        if self.is_paused:
            return self._offset
        return self._offset + (time.time() - (self._start_time or time.time()))

    def is_finished(self) -> bool:
        return self.proc is not None and self.proc.poll() is not None


class MusicPlayer:
    def __init__(self, client: TelegramClient):
        self.client = client
        self.stream = StreamPlayer()
        self.queue: list[dict] = []   # {"media", "title", "duration"}
        self.current_index = -1
        self._eq_bars = [1] * EQ_COLS
        self._eq_lock = threading.Lock()
        self.show_playlist = False
        self._select_buf = ""
        self._select_time = 0.0
        self._pending_advance = False
        # Playback modes
        self.repeat_mode = "off"          # "off" | "all" | "one"
        self.shuffle = False
        self._shuffle_history: list[int] = []   # for prev in shuffle mode

    # ── Queue ──────────────────────────────────────────────────────────

    def add_track(self, media, title: str, duration: float):
        self.queue.append({"media": media, "title": title, "duration": duration})

    # ── Playback ───────────────────────────────────────────────────────

    async def play_index(self, index: int):
        if 0 <= index < len(self.queue):
            self.current_index = index
            await self.stream.start(self.client, self.queue[index]["media"])

    async def stop(self):
        await self.stream.kill()

    async def next_track(self):
        if self.repeat_mode == "one":
            await self.play_index(self.current_index)
            return

        if self.shuffle:
            candidates = [i for i in range(len(self.queue)) if i != self.current_index]
            if candidates:
                self._shuffle_history.append(self.current_index)
                await self.play_index(random.choice(candidates))
            elif self.repeat_mode == "all" and self.queue:
                self._shuffle_history.clear()
                await self.play_index(random.randrange(len(self.queue)))
            else:
                await self.stream.kill()
            return

        nxt = self.current_index + 1
        if nxt < len(self.queue):
            await self.play_index(nxt)
        elif self.repeat_mode == "all":
            await self.play_index(0)
        else:
            await self.stream.kill()

    async def prev_track(self):
        if self.stream.get_position() > 3.0:
            await self.play_index(self.current_index)
            return

        if self.shuffle and self._shuffle_history:
            await self.play_index(self._shuffle_history.pop())
            return

        if self.current_index > 0:
            await self.play_index(self.current_index - 1)
        elif self.repeat_mode == "all" and self.queue:
            await self.play_index(len(self.queue) - 1)

    def cycle_repeat(self):
        order = ("off", "all", "one")
        self.repeat_mode = order[(order.index(self.repeat_mode) + 1) % 3]

    def toggle_shuffle(self):
        self.shuffle = not self.shuffle
        self._shuffle_history.clear()

    async def jump_to_number(self, n: int):
        await self.play_index(n - 1)

    # ── Tick (called from render loop) ─────────────────────────────────

    def tick(self):
        with self._eq_lock:
            if self.stream.is_playing and not self.stream.is_paused:
                self._eq_bars = [
                    max(1, min(8, b + random.randint(-2, 3)))
                    for b in self._eq_bars
                ]
            else:
                self._eq_bars = [max(1, b - 1) for b in self._eq_bars]

        if self._select_buf and (time.time() - self._select_time) > 0.7:
            try:
                asyncio.create_task(self.jump_to_number(int(self._select_buf)))
            except ValueError:
                pass
            self._select_buf = ""

        # Signal render loop to advance when mpv process exits naturally
        if self.stream.is_finished() and self.stream.is_playing:
            self._pending_advance = True

    def push_digit(self, d: str):
        self._select_buf += d
        self._select_time = time.time()

    # ── Render ─────────────────────────────────────────────────────────

    def _render_player(self) -> Panel:
        track = self.queue[self.current_index] if 0 <= self.current_index < len(self.queue) else None
        title = track["title"] if track else "No track loaded"
        duration = float(track["duration"]) if track else 0.0
        pos = min(self.stream.get_position(), duration) if duration > 0 else self.stream.get_position()

        def fmt(s: float) -> str:
            return f"{int(max(0, s) // 60):02d}:{int(max(0, s) % 60):02d}"

        with self._eq_lock:
            bars = list(self._eq_bars)

        eq_rows = []
        for row in range(EQ_HEIGHT, 0, -1):
            line = ""
            for b in bars:
                if b * EQ_HEIGHT / 8 >= row:
                    frac = row / EQ_HEIGHT
                    if frac > 0.65:
                        line += "[bright_green]█[/bright_green]"
                    elif frac > 0.35:
                        line += "[yellow]█[/yellow]"
                    else:
                        line += "[cyan]█[/cyan]"
                else:
                    line += "[dim bright_black]▁[/dim bright_black]"
            eq_rows.append(line)

        filled = max(0, min(int((pos / duration) * BAR_WIDTH) if duration > 0 else 0, BAR_WIDTH))
        if filled < BAR_WIDTH:
            prog = (
                "[green]" + "━" * filled + "[/green]"
                + "[bright_white]╸[/bright_white]"
                + "[dim]" + "─" * max(0, BAR_WIDTH - filled - 1) + "[/dim]"
            )
        else:
            prog = "[green]" + "━" * BAR_WIDTH + "[/green]"

        if self.stream.is_playing and not self.stream.is_paused:
            status = "[bold bright_green]▶  PLAYING[/bold bright_green]"
        elif self.stream.is_paused:
            status = "[bold yellow]⏸  PAUSED[/bold yellow]"
        else:
            status = "[bold red]⏹  STOPPED[/bold red]"

        idx_info = (
            f"[dim][ {self.current_index + 1} / {len(self.queue)} ][/dim]"
            if self.queue else "[dim][no tracks][/dim]"
        )
        select_hint = f"  [bold cyan]→ #{self._select_buf}[/bold cyan]" if self._select_buf else ""

        # Mode badges
        repeat_badge = {
            "off": "",
            "all": "  [bold magenta]⟳ REPEAT ALL[/bold magenta]",
            "one": "  [bold magenta]⟳ REPEAT ONE[/bold magenta]",
        }[self.repeat_mode]
        shuffle_badge = "  [bold blue]⇀ SHUFFLE[/bold blue]" if self.shuffle else ""

        return Panel(
            f"[bold white]{title}[/bold white]   {idx_info}\n\n"
            + "\n".join(eq_rows) + "\n\n"
            + f"[cyan]{fmt(pos)}[/cyan]  {prog}  [dim]{fmt(duration) if duration else '--:--'}[/dim]\n\n"
            + f"  {status}{repeat_badge}{shuffle_badge}{select_hint}\n\n"
            + "[dim]  [P] Pause/Play   [S] Stop   [,/←] Prev   [./→] Next\n"
            + "  [R] Repeat   [X] Shuffle   [L] Playlist   [1-9…] Jump to #   [Q] Menu[/dim]",
            title="[bold yellow]  ♪  Music Player[/bold yellow]",
            border_style="bright_cyan",
            padding=(1, 2),
        )

    def _render_playlist(self) -> Panel:
        table = Table(show_header=True, header_style="bold cyan",
                      box=None, padding=(0, 1), expand=True)
        table.add_column("#", style="dim", width=4, justify="right")
        table.add_column("Title", style="white")
        table.add_column("Duration", style="dim", width=7, justify="right")

        for i, t in enumerate(self.queue):
            dur = float(t["duration"])
            dur_str = f"{int(dur // 60):02d}:{int(dur % 60):02d}" if dur else "--:--"
            num, name = str(i + 1), t["title"]
            if i == self.current_index:
                num = f"[bold bright_green]▶ {i + 1}[/bold bright_green]"
                name = f"[bold bright_green]{name}[/bold bright_green]"
                dur_str = f"[bold bright_green]{dur_str}[/bold bright_green]"
            table.add_row(num, name, dur_str)

        select_hint = (
            f"\n[bold cyan]Jumping to track #{self._select_buf}...[/bold cyan]"
            if self._select_buf else ""
        )

        repeat_badge = {
            "off": "",
            "all": "  [bold magenta]⟳ REPEAT ALL[/bold magenta]",
            "one": "  [bold magenta]⟳ REPEAT ONE[/bold magenta]",
        }[self.repeat_mode]
        shuffle_badge = "  [bold blue]⇀ SHUFFLE[/bold blue]" if self.shuffle else ""

        return Panel(
            table,
            title=(
                f"[bold yellow]  ♪  Playlist  [dim]({len(self.queue)} tracks)[/dim][/bold yellow]"
                + repeat_badge + shuffle_badge + select_hint
            ),
            border_style="bright_cyan",
            padding=(1, 1),
            subtitle="[dim][L] Back   [R] Repeat   [X] Shuffle   [1-9…] Jump to #   [,/←] Prev   [./→] Next   [Q] Menu[/dim]",
        )

    def render(self) -> Panel:
        return self._render_playlist() if self.show_playlist else self._render_player()


async def run_player():
    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.start()

    player = MusicPlayer(client)
    quit_player = threading.Event()
    loop = asyncio.get_event_loop()

    clicked_get_all = False
    first_ready: asyncio.Event | None = None

    @client.on(events.NewMessage(chats=BOT_USERNAME))
    async def handler(event):
        nonlocal clicked_get_all

        if event.out:
            return

        if event.buttons and not clicked_get_all:
            for row in event.buttons:
                for btn in row:
                    if "GET ALL" in btn.text.upper():
                        clicked_get_all = True
                        await event.click(text=btn.text)
                        return

        if not event.file:
            return

        filename = event.file.name or "unknown_file"
        if not (event.audio or filename.lower().endswith(AUDIO_EXTENSIONS)):
            return

        title = Path(filename).stem
        duration = float(getattr(event.file, "duration", 0) or 0)

        player.add_track(event.media, title, duration)

        # First track: start streaming immediately — no buffering wait
        if player.current_index == -1:
            await player.play_index(0)

        if first_ready is not None and not first_ready.is_set():
            first_ready.set()

    def key_listener():
        try:
            while not quit_player.is_set():
                key = readchar.readkey()
                k = key.lower() if len(key) == 1 else key

                if k == "p":
                    player.stream.toggle_pause()
                elif k == "s":
                    asyncio.run_coroutine_threadsafe(player.stop(), loop)
                elif k in (",", readchar.key.LEFT):
                    player._select_buf = ""
                    asyncio.run_coroutine_threadsafe(player.prev_track(), loop)
                elif k in (".", readchar.key.RIGHT):
                    player._select_buf = ""
                    asyncio.run_coroutine_threadsafe(player.next_track(), loop)
                elif k == "l":
                    player.show_playlist = not player.show_playlist
                elif k == "r":
                    player.cycle_repeat()
                elif k == "x":
                    player.toggle_shuffle()
                elif k.isdigit():
                    player.push_digit(k)
                elif k in (readchar.key.ENTER, "\r", "\n"):
                    if player._select_buf:
                        try:
                            n = int(player._select_buf)
                            asyncio.run_coroutine_threadsafe(player.jump_to_number(n), loop)
                        except ValueError:
                            pass
                        player._select_buf = ""
                elif k == "q":
                    asyncio.run_coroutine_threadsafe(player.stop(), loop)
                    quit_player.set()
        except Exception:
            pass

    try:
        while True:
            console.print("\n[bold white]-----------------------------[/bold white]")
            message = console.input(
                "[bold white]Paste Spotify link ('q' to go back): [/bold white]"
            ).strip()

            if not message:
                console.print("[red]Empty input[/red]")
                continue

            if message.lower() in {"q", "quit", "exit"}:
                console.print("[yellow]Returning to menu...[/yellow]")
                break

            clicked_get_all = False
            first_ready = asyncio.Event()
            player.queue.clear()
            player.current_index = -1
            player.show_playlist = False
            player._select_buf = ""
            player.repeat_mode = "off"
            player.shuffle = False
            player._shuffle_history.clear()
            await player.stop()
            quit_player.clear()

            console.print("[dim cyan]Loading...[/dim cyan]")
            await client.send_message(BOT_USERNAME, message)

            try:
                await asyncio.wait_for(first_ready.wait(), timeout=DOWNLOAD_TIMEOUT)
            except asyncio.TimeoutError:
                console.print("[bold red]Timed out waiting for audio.[/bold red]")
                continue

            kt = threading.Thread(target=key_listener, daemon=True)
            kt.start()

            with Live(player.render(), auto_refresh=False, console=console, screen=True) as live:
                while not quit_player.is_set():
                    player.tick()
                    if player._pending_advance:
                        player._pending_advance = False
                        await player.next_track()
                    live.update(player.render(), refresh=True)
                    await asyncio.sleep(0.15)

            if quit_player.is_set():
                console.print("[yellow]Returning to menu...[/yellow]")
                break

    finally:
        await player.stop()
        await client.disconnect()
        if not IS_WINDOWS:
            try:
                os.unlink(MPV_IPC_SOCK)
            except FileNotFoundError:
                pass
