import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd
from core.logger import log

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
        notes: Optional[str] = None
    ) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT OR REPLACE INTO applied_jobs 
                    (platform, job_id, job_title, company, location, job_url, status, notes, applied_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    platform,
                    job_id or "",
                    job_title,
                    company or "Unknown",
                    location or "",
                    job_url,
                    status,
                    notes or "",
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ))
                conn.commit()
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
        salary: Optional[str] = None
    ) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT OR IGNORE INTO scraped_jobs
                    (platform, job_id, job_title, company, location, experience, salary, job_url, scraped_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    platform,
                    job_id or "",
                    job_title,
                    company,
                    location,
                    experience,
                    salary,
                    job_url,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ))
                conn.commit()
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

        csv_applied_path = target_dir / f"applied_jobs_{timestamp}.csv"
        excel_path = target_dir / f"job_report_{timestamp}.xlsx"

        df_applied.to_csv(csv_applied_path, index=False)
        
        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            df_applied.to_excel(writer, sheet_name="Applied Jobs", index=False)
            df_scraped.to_excel(writer, sheet_name="Scraped Jobs", index=False)

        return {
            "csv": str(csv_applied_path),
            "excel": str(excel_path)
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
