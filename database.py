"""
database.py
ماژول مدیریت دیتابیس SQLite برای ربات بازی سنگ‌کاغذقیچی.
نگه‌داری وضعیت بازی‌های فعال، شرکت‌کننده‌ها، انتخاب هر دست و امتیازات
به شکل پایدار (با ری‌استارت ربات از بین نمی‌رود).
"""

import sqlite3
import json
import time
from contextlib import contextmanager

DB_PATH = "rps_games.db"

# -----------------------------------------------------------------
# اتصال و ساخت جدول‌ها
# -----------------------------------------------------------------

@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """ساخت جدول‌های لازم در صورت نبود."""
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS games (
                game_id TEXT PRIMARY KEY,
                chat_id INTEGER,
                message_id INTEGER,
                inline_message_id TEXT,
                status TEXT NOT NULL DEFAULT 'waiting',
                -- وضعیت‌ها: waiting | ready | round_in_progress | finished
                p1_id INTEGER,
                p1_name TEXT,
                p2_id INTEGER,
                p2_name TEXT,
                current_round INTEGER NOT NULL DEFAULT 0,
                p1_score INTEGER NOT NULL DEFAULT 0,
                p2_score INTEGER NOT NULL DEFAULT 0,
                rounds_data TEXT NOT NULL DEFAULT '[]',
                -- rounds_data: لیست JSON از دیکشنری هر دست
                -- مثل [{"p1": "rock", "p2": "scissors", "winner": "p1"}, ...]
                p1_current_choice TEXT,
                p2_current_choice TEXT,
                created_at INTEGER,
                updated_at INTEGER
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_games_chat ON games(chat_id)"
        )


# -----------------------------------------------------------------
# توابع کمکی برای کار با بازی‌ها
# -----------------------------------------------------------------

def create_game(game_id: str, chat_id: int, p1_id: int, p1_name: str):
    now = int(time.time())
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO games (
                game_id, chat_id, status, p1_id, p1_name,
                created_at, updated_at
            ) VALUES (?, ?, 'waiting', ?, ?, ?, ?)
            """,
            (game_id, chat_id, p1_id, p1_name, now, now),
        )


def get_game(game_id: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM games WHERE game_id = ?", (game_id,)
        ).fetchone()
        return dict(row) if row else None


def set_message_ref(game_id: str, chat_id: int = None, message_id: int = None,
                     inline_message_id: str = None):
    """ذخیره مرجع پیام (برای ادیت بعدی) - یا چت معمولی یا اینلاین."""
    with get_conn() as conn:
        if inline_message_id is not None:
            conn.execute(
                "UPDATE games SET inline_message_id = ?, updated_at = ? WHERE game_id = ?",
                (inline_message_id, int(time.time()), game_id),
            )
        else:
            conn.execute(
                "UPDATE games SET chat_id = ?, message_id = ?, updated_at = ? WHERE game_id = ?",
                (chat_id, message_id, int(time.time()), game_id),
            )


def join_game(game_id: str, p2_id: int, p2_name: str) -> bool:
    """
    نفر دوم به بازی می‌پیوندد.
    برمی‌گرداند True اگر موفق بود، False اگر بازی پر بود یا کاربر همون نفر اول بود.
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT p1_id, p2_id FROM games WHERE game_id = ?", (game_id,)
        ).fetchone()
        if not row:
            return False
        if row["p1_id"] == p2_id:
            return False  # نفر اول نمی‌تونه با خودش بازی کنه
        if row["p2_id"] is not None:
            return False  # بازی قبلاً پر شده

        conn.execute(
            "UPDATE games SET p2_id = ?, p2_name = ?, status = 'ready', updated_at = ? WHERE game_id = ?",
            (p2_id, p2_name, int(time.time()), game_id),
        )
        return True


def start_round(game_id: str):
    """شروع یک دست جدید (پاک‌کردن انتخاب‌های قبلی)."""
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE games
            SET status = 'round_in_progress',
                current_round = current_round + 1,
                p1_current_choice = NULL,
                p2_current_choice = NULL,
                updated_at = ?
            WHERE game_id = ?
            """,
            (int(time.time()), game_id),
        )


def set_choice(game_id: str, player_slot: str, choice: str):
    """ثبت انتخاب یک بازیکن (player_slot: 'p1' یا 'p2')."""
    col = "p1_current_choice" if player_slot == "p1" else "p2_current_choice"
    with get_conn() as conn:
        conn.execute(
            f"UPDATE games SET {col} = ?, updated_at = ? WHERE game_id = ?",
            (choice, int(time.time()), game_id),
        )


def finalize_round(game_id: str, p1_choice: str, p2_choice: str, round_winner: str):
    """
    ذخیره نتیجه دست در rounds_data و به‌روزرسانی امتیاز.
    round_winner: 'p1' | 'p2' | 'draw'
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT rounds_data, p1_score, p2_score FROM games WHERE game_id = ?",
            (game_id,),
        ).fetchone()
        rounds = json.loads(row["rounds_data"])
        rounds.append({"p1": p1_choice, "p2": p2_choice, "winner": round_winner})

        p1_score = row["p1_score"] + (1 if round_winner == "p1" else 0)
        p2_score = row["p2_score"] + (1 if round_winner == "p2" else 0)

        conn.execute(
            """
            UPDATE games
            SET rounds_data = ?, p1_score = ?, p2_score = ?,
                p1_current_choice = NULL, p2_current_choice = NULL,
                status = 'ready', updated_at = ?
            WHERE game_id = ?
            """,
            (json.dumps(rounds, ensure_ascii=False), p1_score, p2_score,
             int(time.time()), game_id),
        )


def finish_game(game_id: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE games SET status = 'finished', updated_at = ? WHERE game_id = ?",
            (int(time.time()), game_id),
        )


def get_rounds(game_id: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT rounds_data FROM games WHERE game_id = ?", (game_id,)
        ).fetchone()
        return json.loads(row["rounds_data"]) if row else []
