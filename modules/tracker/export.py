from pathlib import Path
from rich.table import Table
from config.config import settings
from core.logger import console, log
from core.storage import db

def print_stats_table():
    """Displays formatted application metrics and status summary in console."""
    stats = db.get_stats()

    # Applied table
    table = Table(title="📊 Job Application Metrics", header_style="bold magenta")
    table.add_column("Platform", style="cyan")
    table.add_column("Status", style="yellow")
    table.add_column("Count", justify="right", style="green")

    for row in stats["applied"]:
        table.add_row(row["platform"].capitalize(), row["status"], str(row["count(*)"]))

    if not stats["applied"]:
        table.add_row("-", "No applications yet", "0")

    console.print(table)

    # Scraped table
    scrape_table = Table(title="🔍 Scraped Jobs Summary", header_style="bold blue")
    scrape_table.add_column("Platform", style="cyan")
    scrape_table.add_column("Total Scraped Jobs", justify="right", style="green")

    for row in stats["scraped"]:
        scrape_table.add_row(row["platform"].capitalize(), str(row["count(*)"]))

    if not stats["scraped"]:
        scrape_table.add_row("-", "0")

    console.print(scrape_table)

    # Refreshes table
    refresh_table = Table(title="⚡ Profile Boost Refreshes", header_style="bold green")
    refresh_table.add_column("Platform", style="cyan")
    refresh_table.add_column("Last Refreshed At", style="yellow")

    for row in stats["refreshes"]:
        refresh_table.add_row(row["platform"].capitalize(), str(row["max(refreshed_at)"]))

    if not stats["refreshes"]:
        refresh_table.add_row("-", "Never")

    console.print(refresh_table)

def export_reports(target_dir: str = None) -> dict:
    """Exports SQLite job database to CSV and Excel."""
    out_dir = Path(target_dir or settings.reporting.export_dir)
    log.info(f"Exporting application reports to {out_dir}...")
    files = db.export_all(out_dir)
    log.info(f"[green]✓ CSV Exported: {files['csv']}[/green]")
    log.info(f"[green]✓ Excel Exported: {files['excel']}[/green]")
    return files
