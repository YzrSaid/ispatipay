import os
import sys
import webbrowser
import asyncio
from pyfiglet import figlet_format
from rich.console import Console
from rich.panel import Panel

from downloader import run_downloader

console = Console()

APP_NAME = "Ispatipay"
AUTHOR = "Mohammad Aldrin Said"
REPO_URL = "https://github.com/YzrSaid/ispatipay"


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def show_banner():
    banner = figlet_format(APP_NAME, font="big")
    console.print(f"[bold bright_green]{banner}[/bold bright_green]")
    console.print("[bold cyan]--=[ Spotify Downloader CLI ]=--[/bold cyan]\n")

    info = (
        f"[cyan][>][/cyan] Github  : [green]{REPO_URL}[/green]\n"
        f"[cyan][>][/cyan] Author  : [green]{AUTHOR}[/green]\n"
        f"[cyan][>][/cyan] Version : [green]1.0[/green]"
    )

    console.print(Panel(info, border_style="bright_black"))


def show_menu():
    menu = (
        "[bold green][1][/bold green] Start Downloader\n"
        "[bold green][2][/bold green] View Source Code\n"
        "[bold green][3][/bold green] About / Help\n\n"
        "[bold red][0][/bold red] Exit"
    )

    console.print(
        Panel(
            menu, title="[bold yellow]Main Menu[/bold yellow]", border_style="white")
    )


def about():
    clear()
    show_banner()

    text = (
        "[bold green]Ispatipay[/bold green]\n\n"
        "A CLI tool to download Spotify music via Telegram bot.\n\n"
        "[cyan]Features:[/cyan]\n"
        "- Clean CLI UI\n"
        "- Auto audio download\n"
        "- Loop-based downloader\n\n"
        "[cyan]Usage:[/cyan]\n"
        "1. Choose Start Downloader\n"
        "2. Paste Spotify link\n"
        "3. Wait for bot response\n"
        "4. Audio downloads automatically\n"
    )

    console.print(Panel(text, title="About / Help", border_style="cyan"))
    input("\nPress Enter to go back...")


def view_source():
    console.print(
        f"\n[bold cyan]Opening:[/bold cyan] [green]{REPO_URL}[/green]")
    webbrowser.open(REPO_URL)
    input("\nPress Enter to continue...")


def start_downloader():
    clear()
    show_banner()
    console.print("[bold green]Starting downloader...[/bold green]\n")
    asyncio.run(run_downloader())


def main():
    while True:
        clear()
        show_banner()
        show_menu()

        choice = input("\n[>] Select Option: ").strip()

        if choice == "1":
            start_downloader()
        elif choice == "2":
            view_source()
        elif choice == "3":
            about()
        elif choice == "0":
            console.print("\n[bold red]Exiting...[/bold red]")
            sys.exit()
        else:
            console.print("[red]Invalid option[/red]")
            input("Press Enter...")


if __name__ == "__main__":
    main()
