import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd
from core.logger import log
from config.config import settings

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "jobs.db"

class Storage:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS applied_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    job_id TEXT,
                    job_title TEXT NOT NULL,
                    company TEXT,
                    location TEXT,
                    job_url TEXT UNIQUE NOT NULL,
                    status TEXT NOT NULL,
                    notes TEXT,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS scraped_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    job_id TEXT,
                    job_title TEXT NOT NULL,
                    company TEXT,
                    location TEXT,
                    experience TEXT,
                    salary TEXT,
                    job_url TEXT UNIQUE NOT NULL,
                    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS profile_refreshes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    action_summary TEXT,
                    refreshed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS training_interactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    job_title TEXT,
                    company TEXT,
                    field_type TEXT,
                    question_or_label TEXT NOT NULL,
                    options_json TEXT,
                    chosen_answer TEXT NOT NULL,
                    source TEXT,
                    context_snippet TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Auto-migrate schema columns if missing
            for col_sql in [
                "ALTER TABLE applied_jobs ADD COLUMN match_score REAL DEFAULT 0.0",
                "ALTER TABLE scraped_jobs ADD COLUMN match_score REAL DEFAULT 0.0",
                "ALTER TABLE scraped_jobs ADD COLUMN snippet TEXT DEFAULT ''",
            ]:
                try:
                    cursor.execute(col_sql)
                except Exception:
                    pass

            conn.commit()

    def is_already_applied(self, platform: str, job_url: str, job_id: Optional[str] = None) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if job_id:
                cursor.execute(
                    "SELECT 1 FROM applied_jobs WHERE platform = ? AND (job_url = ? OR job_id = ?)",
                    (platform, job_url, job_id)
                )
            else:
                cursor.execute(
                    "SELECT 1 FROM applied_jobs WHERE platform = ? AND job_url = ?",
                    (platform, job_url)
                )
            return cursor.fetchone() is not None

    def record_applied_job(
        self,
        platform: str,
        job_title: str,
        company: str,
        job_url: str,
        status: str,
        job_id: Optional[str] = None,
        location: Optional[str] = None,
        notes: Optional[str] = None,
        match_score: float = 0.0
    ) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT OR REPLACE INTO applied_jobs 
                    (platform, job_id, job_title, company, location, job_url, status, notes, match_score, applied_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    platform,
                    job_id or "",
                    job_title,
                    company or "Unknown",
                    location or "",
                    job_url,
                    status,
                    notes or "",
                    float(match_score or 0.0),
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ))
                conn.commit()

                # Dispatch real-time cloud notifications (Discord / Telegram) if submitted
                if status in ("APPLIED", "APPLIED_PENDING_CONFIRMATION", "SUBMITTED"):
                    try:
                        from core.notifications import notifier
                        notifier.notify_application_submitted(
                            platform=platform,
                            job_title=job_title,
                            company=company,
                            job_url=job_url,
                            status=status,
                            match_score=float(match_score or 0.0),
                            notes=notes or ""
                        )
                    except Exception:
                        pass

                return True
            except Exception as e:
                log.error(f"Failed to record applied job: {e}")
                return False

    def record_scraped_job(
        self,
        platform: str,
        job_title: str,
        company: str,
        job_url: str,
        job_id: Optional[str] = None,
        location: Optional[str] = None,
        experience: Optional[str] = None,
        salary: Optional[str] = None,
        match_score: float = 0.0,
        snippet: Optional[str] = None
    ) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT OR IGNORE INTO scraped_jobs
                    (platform, job_id, job_title, company, location, experience, salary, job_url, match_score, snippet, scraped_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    platform,
                    job_id or "",
                    job_title,
                    company,
                    location,
                    experience,
                    salary,
                    job_url,
                    float(match_score or 0.0),
                    snippet or "",
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ))
                conn.commit()

                # Dispatch real-time cloud notifications (Discord / Telegram) if submitted
                if status in ("APPLIED", "APPLIED_PENDING_CONFIRMATION", "SUBMITTED"):
                    try:
                        from core.notifications import notifier
                        notifier.notify_application_submitted(
                            platform=platform,
                            job_title=job_title,
                            company=company,
                            job_url=job_url,
                            status=status,
                            match_score=float(match_score or 0.0),
                            notes=notes or ""
                        )
                    except Exception:
                        pass

                return True
            except Exception as e:
                log.error(f"Failed to record scraped job: {e}")
                return False

    def record_profile_refresh(self, platform: str, summary: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO profile_refreshes (platform, action_summary) VALUES (?, ?)",
                (platform, summary)
            )
            conn.commit()

    def get_stats(self) -> Dict[str, any]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT platform, status, count(*) FROM applied_jobs GROUP BY platform, status")
            applied_stats = cursor.fetchall()
            
            cursor.execute("SELECT platform, count(*) FROM scraped_jobs GROUP BY platform")
            scraped_stats = cursor.fetchall()

            cursor.execute("SELECT platform, max(refreshed_at) FROM profile_refreshes GROUP BY platform")
            refresh_stats = cursor.fetchall()

            return {
                "applied": [dict(row) for row in applied_stats],
                "scraped": [dict(row) for row in scraped_stats],
                "refreshes": [dict(row) for row in refresh_stats]
            }

    def export_all(self, target_dir: Path) -> Dict[str, str]:
        target_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        with self._get_connection() as conn:
            df_applied = pd.read_sql_query("SELECT * FROM applied_jobs ORDER BY applied_at DESC", conn)
            df_scraped = pd.read_sql_query("SELECT * FROM scraped_jobs ORDER BY scraped_at DESC", conn)
            df_refreshes = pd.read_sql_query("SELECT * FROM profile_refreshes ORDER BY refreshed_at DESC", conn)

        csv_applied_path = target_dir / f"applied_jobs_{timestamp}.csv"
        excel_path = target_dir / f"job_report_{timestamp}.xlsx"
        chart_path = target_dir / f"dashboard_chart_{timestamp}.png"
        html_path = target_dir / f"executive_summary_{timestamp}.html"

        # 1. Export CSV & Excel
        df_applied.to_csv(csv_applied_path, index=False)
        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            df_applied.to_excel(writer, sheet_name="Applied Jobs", index=False)
            df_scraped.to_excel(writer, sheet_name="Scraped Jobs", index=False)
            df_refreshes.to_excel(writer, sheet_name="Profile Boosts", index=False)

        # 2. Generate Visual Chart with Matplotlib
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(18, 5.5), facecolor="#0f172a")

            # Chart 1: Status Distribution
            if not df_applied.empty and "status" in df_applied.columns:
                status_counts = df_applied["status"].value_counts()
                colors = ["#10b981" if "APPLIED" in s else "#f59e0b" if "ALREADY" in s else "#38bdf8" if "PENDING" in s else "#ef4444" for s in status_counts.index]
                bars = ax1.barh(status_counts.index, status_counts.values, color=colors, edgecolor="#334155", height=0.6)
                ax1.set_title("Application Status Breakdown", color="#f8fafc", fontsize=13, fontweight="bold", pad=12)
                ax1.set_xlabel("Number of Jobs", color="#94a3b8", fontsize=10)
                ax1.tick_params(colors="#cbd5e1", labelsize=9)
                ax1.set_facecolor("#1e293b")
                ax1.grid(axis="x", color="#334155", linestyle="--", alpha=0.6)
                for bar in bars:
                    width = bar.get_width()
                    ax1.text(width + 0.3, bar.get_y() + bar.get_height() / 2, f"{int(width)}", ha="left", va="center", color="#f8fafc", fontweight="bold", fontsize=9)
            else:
                ax1.text(0.5, 0.5, "No Applications Recorded", color="#94a3b8", ha="center", va="center", fontsize=12)
                ax1.set_facecolor("#1e293b")

            # Chart 2: Platform Distribution Donut
            if not df_applied.empty and "platform" in df_applied.columns:
                platform_counts = df_applied["platform"].value_counts()
                plat_colors = ["#0077b5", "#3b82f6", "#10b981", "#8b5cf6"][:len(platform_counts)]
                wedges, texts, autotexts = ax2.pie(
                    platform_counts.values,
                    labels=[p.capitalize() for p in platform_counts.index],
                    autopct="%1.1f%%",
                    colors=plat_colors,
                    startangle=140,
                    wedgeprops={"edgecolor": "#0f172a", "width": 0.5},
                    textprops={"color": "#f8fafc", "fontsize": 10}
                )
                for autotext in autotexts:
                    autotext.set_color("#ffffff")
                    autotext.set_fontweight("bold")
                ax2.set_title("Applications by Platform", color="#f8fafc", fontsize=13, fontweight="bold", pad=12)
                ax2.set_facecolor("#0f172a")
            else:
                ax2.text(0.5, 0.5, "No Data", color="#94a3b8", ha="center", va="center", fontsize=12)

            # Chart 3: AI Compatibility Scores (JobBERT + bge-reranker)
            scores = []
            if not df_applied.empty and "match_score" in df_applied.columns:
                scores = [float(s) * 100 for s in df_applied["match_score"] if pd.notnull(s) and float(s) > 0]

            if scores:
                bins = [0, 50, 70, 85, 100]
                bin_labels = ["<50%", "50-70%", "70-85%", "85-100%"]
                counts, _ = pd.cut(scores, bins=bins, labels=bin_labels, include_lowest=True).value_counts().sort_index(), None
                score_colors = ["#ef4444", "#f59e0b", "#38bdf8", "#10b981"]
                ax3.bar(bin_labels, counts.values, color=score_colors, edgecolor="#334155", width=0.55)
                ax3.set_title("AI Match Score Distribution", color="#f8fafc", fontsize=13, fontweight="bold", pad=12)
                ax3.set_xlabel("Relevance Bracket", color="#94a3b8", fontsize=10)
                ax3.set_ylabel("Jobs", color="#94a3b8", fontsize=10)
                ax3.tick_params(colors="#cbd5e1", labelsize=9)
                ax3.set_facecolor("#1e293b")
                ax3.grid(axis="y", color="#334155", linestyle="--", alpha=0.6)
            else:
                ax3.text(0.5, 0.5, "AI Semantic Matcher\nJobBERT & bge-reranker Active", color="#38bdf8", ha="center", va="center", fontsize=11, fontweight="bold")
                ax3.set_facecolor("#1e293b")

            plt.tight_layout()
            plt.savefig(chart_path, dpi=160, facecolor=fig.get_facecolor(), bbox_inches="tight")
            # Save static latest copy
            latest_chart = target_dir / "latest_dashboard.png"
            plt.savefig(latest_chart, dpi=160, facecolor=fig.get_facecolor(), bbox_inches="tight")
            plt.close(fig)
        except Exception as chart_err:
            log.debug(f"Chart generation note: {chart_err}")

        # 3. Generate Executive HTML Summary
        try:
            total_applied = len(df_applied[df_applied["status"].isin(["APPLIED", "APPLIED_PENDING_CONFIRMATION"])]) if not df_applied.empty else 0
            total_tracked = len(df_applied) if not df_applied.empty else 0
            total_scraped = len(df_scraped) if not df_scraped.empty else 0

            rows_html = ""
            if not df_applied.empty:
                for _, r in df_applied.head(50).iterrows():
                    status_badge = "background:#065f46;color:#6ee7b7;" if "APPLIED" in str(r.get("status", "")) else "background:#854d0e;color:#fde047;"
                    raw_score = r.get("match_score", 0.0)
                    try:
                        score_val = float(raw_score) if raw_score is not None else 0.0
                    except (ValueError, TypeError):
                        score_val = 0.0

                    if score_val >= 0.80:
                        score_badge = f'<span style="padding:4px 8px;border-radius:12px;font-size:12px;font-weight:600;background:#065f46;color:#6ee7b7;">{score_val*100:.1f}%</span>'
                    elif score_val >= 0.60:
                        score_badge = f'<span style="padding:4px 8px;border-radius:12px;font-size:12px;font-weight:600;background:#0369a1;color:#7dd3fc;">{score_val*100:.1f}%</span>'
                    elif score_val > 0.0:
                        score_badge = f'<span style="padding:4px 8px;border-radius:12px;font-size:12px;font-weight:600;background:#854d0e;color:#fde047;">{score_val*100:.1f}%</span>'
                    else:
                        score_badge = '<span style="color:#64748b;font-size:12px;">N/A</span>'

                    rows_html += f"""
                    <tr style="border-bottom:1px solid #334155;">
                        <td style="padding:10px 14px;color:#38bdf8;font-weight:600;">{str(r.get('platform', '')).capitalize()}</td>
                        <td style="padding:10px 14px;color:#f8fafc;font-weight:600;"><a href="{r.get('job_url', '#')}" target="_blank" style="color:#f8fafc;text-decoration:none;">{r.get('job_title', 'Untitled')}</a></td>
                        <td style="padding:10px 14px;color:#cbd5e1;">{r.get('company', '-')}</td>
                        <td style="padding:10px 14px;">{score_badge}</td>
                        <td style="padding:10px 14px;"><span style="padding:4px 10px;border-radius:12px;font-size:12px;font-weight:600;{status_badge}">{r.get('status', '')}</span></td>
                        <td style="padding:10px 14px;color:#94a3b8;font-size:13px;">{r.get('applied_at', '')}</td>
                    </tr>
                    """

            html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Auto-Browser Executive Report</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 24px; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155; padding-bottom: 16px; margin-bottom: 24px; }}
        .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }}
        .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 18px; }}
        .card h4 {{ margin: 0 0 8px 0; color: #94a3b8; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px; }}
        .card p {{ margin: 0; font-size: 28px; font-weight: 700; color: #38bdf8; }}
        .chart-box {{ background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 18px; margin-bottom: 24px; text-align: center; }}
        table {{ width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 10px; overflow: hidden; }}
        th {{ background: #334155; color: #94a3b8; text-align: left; padding: 12px 14px; font-size: 12px; text-transform: uppercase; }}
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1 style="margin:0;font-size:24px;color:#f8fafc;">🤖 Auto-Browser Executive Job Report</h1>
            <p style="margin:4px 0 0 0;color:#94a3b8;font-size:14px;">Candidate: {settings.profile.first_name} {settings.profile.last_name} | Generated: {timestamp}</p>
        </div>
        <div style="background:#1e293b;border:1px solid #334155;padding:8px 16px;border-radius:8px;font-size:13px;color:#10b981;font-weight:600;">
            ✓ Autonomous RPA Suite Active
        </div>
    </div>
    <div class="cards">
        <div class="card"><h4>Successfully Applied</h4><p style="color:#10b981;">{total_applied}</p></div>
        <div class="card"><h4>Total Tracked</h4><p>{total_tracked}</p></div>
        <div class="card"><h4>Scraped Database</h4><p style="color:#818cf8;">{total_scraped}</p></div>
        <div class="card"><h4>Semantic Match Models</h4><p style="color:#38bdf8;font-size:16px;margin-top:6px;">JobBERT &amp; BGE-Reranker</p></div>
    </div>
    <div class="chart-box">
        <h3 style="margin:0 0 16px 0;color:#f8fafc;font-size:16px;">Visual Analytics Dashboard</h3>
        <img src="dashboard_chart_{timestamp}.png" alt="Analytics Chart" style="max-width:100%;border-radius:8px;">
    </div>
    <div style="background:#1e293b;border:1px solid #334155;border-radius:10px;padding:16px;margin-bottom:24px;">
        <h3 style="margin:0 0 16px 0;color:#f8fafc;font-size:16px;">Latest Job Applications</h3>
        <table>
            <thead><tr><th>Platform</th><th>Job Title</th><th>Company</th><th>AI Match</th><th>Status</th><th>Timestamp</th></tr></thead>
            <tbody>{rows_html if rows_html else '<tr><td colspan="6" style="padding:20px;text-align:center;color:#94a3b8;">No applications recorded yet.</td></tr>'}</tbody>
        </table>
    </div>
</body>
</html>"""
            html_path.write_text(html_content, encoding="utf-8")
            # Save static latest copy
            latest_html = target_dir / "latest_report.html"
            latest_html.write_text(html_content, encoding="utf-8")
        except Exception as html_err:
            log.error(f"HTML generation error: {html_err}", exc_info=True)

        return {
            "csv": str(csv_applied_path),
            "excel": str(excel_path),
            "chart": str(chart_path),
            "html": str(html_path)
        }

    def record_interaction(
        self,
        platform: str,
        question: str,
        answer: str,
        field_type: str = "text",
        options: Optional[List[str]] = None,
        job_title: str = "",
        company: str = "",
        source: str = "ai_or_heuristic",
        context: str = ""
    ) -> bool:
        """Records an application form screening Q&A or field choice for ML dataset fine-tuning."""
        if not question or not answer:
            return False
        import json
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO training_interactions
                    (platform, job_title, company, field_type, question_or_label, options_json, chosen_answer, source, context_snippet)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    platform,
                    job_title,
                    company,
                    field_type,
                    question.strip(),
                    json.dumps(options) if options else "",
                    str(answer).strip(),
                    source,
                    context[:500] if context else ""
                ))
                conn.commit()

                # Dispatch real-time cloud notifications (Discord / Telegram) if submitted
                if status in ("APPLIED", "APPLIED_PENDING_CONFIRMATION", "SUBMITTED"):
                    try:
                        from core.notifications import notifier
                        notifier.notify_application_submitted(
                            platform=platform,
                            job_title=job_title,
                            company=company,
                            job_url=job_url,
                            status=status,
                            match_score=float(match_score or 0.0),
                            notes=notes or ""
                        )
                    except Exception:
                        pass

                return True
            except Exception as e:
                log.debug(f"Failed to record interaction: {e}")
                return False

    def export_training_dataset(self, output_path: Optional[Path] = None) -> Path:
        """
        Exports all recorded interactions to a Hugging Face / Alpaca format JSONL file
        ready for direct fine-tuning on Google Colab or Unsloth.
        """
        import json
        out_file = output_path or (self.db_path.parent / "training_dataset.jsonl")
        out_file.parent.mkdir(parents=True, exist_ok=True)

        system_prompt = (
            "You are an expert AI autonomous job application agent for candidate Avinash Talpade, "
            "a DevOps and Cloud Engineer with 3.6 years experience. Answer recruiter screening questions "
            "accurately, professionally, and truthfully according to the candidate profile."
        )

        # 1. Load existing samples to ensure dataset is cumulative across CI/CD runs
        existing_entries = []
        seen_keys = set()
        if out_file.exists():
            try:
                for line in out_file.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        item = json.loads(line)
                        k = (item.get("input", "").strip(), item.get("output", "").strip())
                        if k not in seen_keys:
                            seen_keys.add(k)
                            existing_entries.append(item)
            except Exception as e:
                log.warning(f"Error reading existing dataset ({e}), starting fresh merge.")

        # 2. Extract new interactions from database
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM training_interactions ORDER BY id ASC")
            rows = cursor.fetchall()

        new_count = 0
        for row in rows:
            opts = json.loads(row["options_json"]) if row["options_json"] else []
            options_str = f"\nAvailable Options: {', '.join(opts)}" if opts else ""
            user_instruction = (
                f"Recruiter Question: '{row['question_or_label']}'\n"
                f"Field Type: {row['field_type']}{options_str}"
            )
            if row["context_snippet"]:
                user_instruction += f"\nContext: {row['context_snippet']}"

            ans = str(row["chosen_answer"] or "")
            k = (user_instruction.strip(), ans.strip())
            if k not in seen_keys:
                seen_keys.add(k)
                existing_entries.append({
                    "instruction": system_prompt,
                    "input": user_instruction,
                    "output": ans
                })
                new_count += 1

        # 3. Only write if we have entries (never wipe out file with 0 bytes)
        if existing_entries:
            with open(out_file, "w", encoding="utf-8") as f:
                for item in existing_entries:
                    f.write(json.dumps(item) + "\n")
            log.info(f"[bold green]✓ Dataset preserved & synchronized ({len(existing_entries)} total samples, {new_count} new) at {out_file}![/bold green]")
        else:
            log.info(f"No interactions found to export; existing dataset file maintained as is.")

        return out_file

db = Storage()
