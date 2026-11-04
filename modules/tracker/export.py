from pathlib import Path
from rich.table import Table
from config.config import settings
from core.logger import console, log
from core.storage import db

def print_stats_table():
    """Displays formatted application metrics and status summary in console."""
    stats = db.get_stats()

    # 1. Confirmed Submitted Applications (User Requested: Submitted Report Only)
    sub_table = Table(title="🚀 Confirmed Submitted Applications", header_style="bold green")
    sub_table.add_column("Platform", style="cyan", justify="left")
    sub_table.add_column("Status", style="bold green", justify="center")
    sub_table.add_column("Total Submitted", justify="right", style="bold green")

    total_submitted = 0
    submitted_rows = stats.get("submitted", [])
    for row in submitted_rows:
        count = row.get("count", 0)
        sub_table.add_row(row["platform"].capitalize(), "SUBMITTED", str(count))
        total_submitted += count

    if not submitted_rows:
        sub_table.add_row("-", "No submissions yet", "0")
    else:
        sub_table.add_section()
        sub_table.add_row("All Platforms", "TOTAL SUBMITTED", str(total_submitted), style="bold yellow")

    console.print(sub_table)

    # 2. Detailed Recent Submissions Table
    recent = stats.get("recent_submissions", [])
    if recent:
        recent_table = Table(title="📑 Recently Submitted Applications (Proof & Grounding)", header_style="bold cyan")
        recent_table.add_column("Platform", style="cyan")
        recent_table.add_column("Company", style="bold magenta")
        recent_table.add_column("Role", style="white")
        recent_table.add_column("AI Match", justify="center", style="bold green")
        recent_table.add_column("Status", justify="center", style="bold green")
        recent_table.add_column("Submitted At", style="yellow")

        for r in recent:
            score = r.get("match_score", 0.0)
            score_str = f"{score*100:.1f}%" if score and score > 0 else "N/A"
            status_label = r.get("status", "SUBMITTED")
            recent_table.add_row(
                str(r.get("platform", "")).capitalize(),
                str(r.get("company", "Unknown")),
                str(r.get("job_title", "Unknown")),
                score_str,
                status_label,
                str(r.get("applied_at", ""))
            )
        console.print(recent_table)

    # 3. Scraped table
    scrape_table = Table(title="🔍 Scraped Jobs Summary", header_style="bold blue")
    scrape_table.add_column("Platform", style="cyan")
    scrape_table.add_column("Total Scraped Jobs", justify="right", style="green")

    for row in stats.get("scraped", []):
        scrape_table.add_row(row["platform"].capitalize(), str(row["count(*)"]))

    if not stats.get("scraped"):
        scrape_table.add_row("-", "0")

    console.print(scrape_table)

    # 4. Refreshes table
    refresh_table = Table(title="⚡ Profile Boost Refreshes", header_style="bold green")
    refresh_table.add_column("Platform", style="cyan")
    refresh_table.add_column("Last Refreshed At", style="yellow")

    for row in stats.get("refreshes", []):
        refresh_table.add_row(row["platform"].capitalize(), str(row["max(refreshed_at)"]))

    if not stats.get("refreshes"):
        refresh_table.add_row("-", "Never")

    console.print(refresh_table)

def export_reports(target_dir: str = None) -> dict:
    """Exports SQLite job database to CSV, Excel, Visual Analytics Chart PNG, and Executive HTML Report."""
    out_dir = Path(target_dir or settings.reporting.export_dir)
    log.info(f"Exporting application reports to {out_dir}...")
    files = db.export_all(out_dir)
    log.info(f"[green]✓ CSV Exported: {files.get('csv')}[/green]")
    log.info(f"[green]✓ Excel Exported: {files.get('excel')}[/green]")
    if files.get("chart"):
        log.info(f"[green]✓ Visual Analytics Chart: {files.get('chart')}[/green]")
    if files.get("html"):
        log.info(f"[green]✓ Executive HTML Report: {files.get('html')}[/green]")
    return files
