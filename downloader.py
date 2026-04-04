import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.live import Live
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from telethon import TelegramClient, events

load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_USERNAME = os.getenv("BOT_USERNAME")
SESSION = "telegram_session"

DOWNLOAD_PATH = Path.home() / "Downloads" / "telegram_downloads"
DOWNLOAD_PATH.mkdir(parents=True, exist_ok=True)

AUDIO_EXTENSIONS = (".mp3", ".m4a", ".wav", ".flac", ".ogg", ".aac")
DOWNLOAD_TIMEOUT = 180

console = Console()


async def run_downloader():
    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.start()

    console.print(f"\n[bold cyan]Save path:[/bold cyan] [green]{DOWNLOAD_PATH}[/green]")

    clicked_get_all = False
    batch_done_event = None
    active_downloads = 0
    downloaded_any = False

    progress = Progress(
        TextColumn("[bold cyan]{task.fields[filename]}", justify="left"),
        BarColumn(),
        TaskProgressColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
    )

    def make_progress_callback(task_id: int):
        def callback(received: int, total: int):
            progress.update(task_id, completed=received, total=total or 0)
        return callback

    @client.on(events.NewMessage(chats=BOT_USERNAME))
    async def handler(event):
        nonlocal clicked_get_all, batch_done_event, active_downloads, downloaded_any

        if event.out:
            return

        if event.raw_text:
            console.print(f"\n[bold magenta]Bot:[/bold magenta] {event.raw_text}")

        # Click "GET ALL" if the bot offers a batch download button
        if event.buttons and not clicked_get_all:
            for row in event.buttons:
                for button in row:
                    if "GET ALL" in button.text.upper():
                        console.print("[yellow]Clicking GET ALL...[/yellow]")
                        clicked_get_all = True
                        await event.click(text=button.text)
                        return

        if not event.file:
            return

        filename = event.file.name or "unknown_file"
        is_audio = event.audio or filename.lower().endswith(AUDIO_EXTENSIONS)

        if not is_audio:
            console.print(f"[dim]Skipped:[/dim] {filename}")
            return

        active_downloads += 1
        downloaded_any = True

        task_id = progress.add_task(
            "download",
            filename=filename,
            total=event.file.size or 0,
            completed=0,
        )

        try:
            path = await event.download_media(
                file=str(DOWNLOAD_PATH),
                progress_callback=make_progress_callback(task_id),
            )
            progress.update(task_id, completed=event.file.size or 0)
            console.print(f"[bold green]Downloaded:[/bold green] {path}")

        except Exception as e:
            console.print(f"[bold red]Download failed:[/bold red] {filename} -> {e}")

        finally:
            active_downloads -= 1
            # Signal batch completion once all concurrent downloads finish
            if batch_done_event is not None and active_downloads == 0 and downloaded_any:
                batch_done_event.set()

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
            downloaded_any = False
            active_downloads = 0
            batch_done_event = asyncio.Event()
            progress.tasks.clear()

            console.print("[cyan]Sending link to bot...[/cyan]")
            await client.send_message(BOT_USERNAME, message)
            console.print("[cyan]Waiting for bot response and downloads...[/cyan]")

            try:
                with Live(progress, refresh_per_second=10, console=console):
                    await asyncio.wait_for(batch_done_event.wait(), timeout=DOWNLOAD_TIMEOUT)

                console.print("[bold green]All downloads completed.[/bold green]")

                again = console.input(
                    "[bold cyan]Download another? (y/n): [/bold cyan]"
                ).strip().lower()
                if again not in {"y", "yes"}:
                    console.print("[yellow]Returning to menu...[/yellow]")
                    break

            except asyncio.TimeoutError:
                console.print("[bold red]Timed out waiting for downloads.[/bold red]")

    finally:
        await client.disconnect()
