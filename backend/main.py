
import os
import sqlite3
import hashlib
import secrets
from pathlib import Path
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, EmailStr

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "smartspend.db"

SECRET_KEY = os.getenv("SMARTSPEND_SECRET")
if not SECRET_KEY:
    SECRET_KEY = secrets.token_hex(32)
    print("WARNING: Using temporary JWT secret. Set SMARTSPEND_SECRET for stable tokens.")

ALGORITHM = "HS256"
TOKEN_HOURS = 8

app = FastAPI(
    title="SmartSpend API",
    description="Personal Finance Manager REST API",
    version="1.0.0",
)

security = HTTPBearer()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


def get_db():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db():
    with get_db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            salt TEXT NOT NULL,
            password_hash TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('Income', 'Expense')),
            category TEXT NOT NULL,
            amount REAL NOT NULL CHECK(amount > 0),
            note TEXT NOT NULL DEFAULT '',
            date TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            month TEXT NOT NULL,
            category TEXT NOT NULL,
            amount REAL NOT NULL CHECK(amount > 0),
            UNIQUE(user_id, month, category),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_transactions_user_date
        ON transactions(user_id, date);

        CREATE INDEX IF NOT EXISTS idx_budgets_user_month
        ON budgets(user_id, month);
        """)


init_db()


class RegisterInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TransactionInput(BaseModel):
    kind: str
    category: str = Field(min_length=1, max_length=50)
    amount: float = Field(gt=0, le=1_000_000_000)
    note: str = Field(default="", max_length=250)
    date: str


class BudgetInput(BaseModel):
    month: str
    category: str = Field(min_length=1, max_length=50)
    amount: float = Field(gt=0, le=1_000_000_000)


def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        310_000,
    ).hex()


def create_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user_id),
            "iat": now,
            "exp": now + timedelta(hours=TOKEN_HOURS),
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> int:
    try:
        payload = jwt.decode(
            credentials.credentials,
            SECRET_KEY,
            algorithms=[ALGORITHM],
        )
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, ValueError, KeyError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    with get_db() as con:
        user = con.execute(
            "SELECT id FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    return user_id


def validate_date(value: str):
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=400,
            detail="Date must use YYYY-MM-DD format",
        )


def validate_month(value: str):
    try:
        datetime.strptime(value, "%Y-%m")
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=400,
            detail="Month must use YYYY-MM format",
        )


@app.get("/")
def home():
    return {
        "message": "Welcome to SmartSpend API",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/api/health")
def health():
    return {"status": "healthy"}


@app.post("/api/register", status_code=201)
def register(data: RegisterInput):
    email = str(data.email).strip().lower()
    salt = secrets.token_hex(16)
    password_hash = hash_password(data.password, salt)

    try:
        with get_db() as con:
            cur = con.execute(
                """
                INSERT INTO users (email, salt, password_hash)
                VALUES (?, ?, ?)
                """,
                (email, salt, password_hash),
            )
            user_id = cur.lastrowid
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Email is already registered")

    return {"message": "Registration successful", "user_id": user_id}


@app.post("/api/login")
def login(data: LoginInput):
    email = str(data.email).strip().lower()

    with get_db() as con:
        user = con.execute(
            "SELECT * FROM users WHERE email = ?",
            (email,),
        ).fetchone()

    if user is None:
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    entered_hash = hash_password(data.password, user["salt"])

    if not secrets.compare_digest(entered_hash, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    return {
        "access_token": create_token(user["id"]),
        "token_type": "bearer",
        "expires_in": TOKEN_HOURS * 3600,
    }


@app.get("/api/me")
def get_me(user_id: int = Depends(get_current_user)):
    with get_db() as con:
        user = con.execute(
            "SELECT id, email FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

    return dict(user)


@app.get("/api/transactions")
def get_transactions(user_id: int = Depends(get_current_user)):
    with get_db() as con:
        rows = con.execute(
            """
            SELECT id, kind, category, amount, note, date
            FROM transactions
            WHERE user_id = ?
            ORDER BY date DESC, id DESC
            """,
            (user_id,),
        ).fetchall()

    return [dict(row) for row in rows]


@app.post("/api/transactions", status_code=201)
def add_transaction(
    data: TransactionInput,
    user_id: int = Depends(get_current_user),
):
    if data.kind not in ("Income", "Expense"):
        raise HTTPException(status_code=400, detail="Type must be Income or Expense")

    category = data.category.strip()
    if not category:
        raise HTTPException(status_code=400, detail="Category is required")

    validate_date(data.date)

    with get_db() as con:
        cur = con.execute(
            """
            INSERT INTO transactions
            (user_id, kind, category, amount, note, date)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, data.kind, category, data.amount, data.note.strip(), data.date),
        )
        transaction_id = cur.lastrowid

    return {
        "message": "Transaction added successfully",
        "id": transaction_id,
    }


@app.delete("/api/transactions/{transaction_id}")
def delete_transaction(
    transaction_id: int,
    user_id: int = Depends(get_current_user),
):
    with get_db() as con:
        cur = con.execute(
            "DELETE FROM transactions WHERE id = ? AND user_id = ?",
            (transaction_id, user_id),
        )

        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Transaction not found")

    return {"message": "Transaction deleted successfully"}


@app.get("/api/budgets")
def get_budgets(user_id: int = Depends(get_current_user)):
    with get_db() as con:
        rows = con.execute(
            """
            SELECT
                b.id,
                b.month,
                b.category,
                b.amount,
                COALESCE(SUM(t.amount), 0) AS spent
            FROM budgets b
            LEFT JOIN transactions t
                ON t.user_id = b.user_id
                AND t.category = b.category
                AND substr(t.date, 1, 7) = b.month
                AND t.kind = 'Expense'
            WHERE b.user_id = ?
            GROUP BY b.id, b.month, b.category, b.amount
            ORDER BY b.month DESC, b.category
            """,
            (user_id,),
        ).fetchall()

    result = []
    for row in rows:
        item = dict(row)
        item["remaining"] = round(item["amount"] - item["spent"], 2)
        item["spent"] = round(item["spent"], 2)
        result.append(item)

    return result


@app.post("/api/budgets")
def save_budget(
    data: BudgetInput,
    user_id: int = Depends(get_current_user),
):
    validate_month(data.month)
    category = data.category.strip()

    if not category:
        raise HTTPException(status_code=400, detail="Category is required")

    with get_db() as con:
        con.execute(
            """
            INSERT INTO budgets (user_id, month, category, amount)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, month, category)
            DO UPDATE SET amount = excluded.amount
            """,
            (user_id, data.month, category, data.amount),
        )

    return {"message": "Budget saved successfully"}


@app.get("/api/summary")
def get_summary(
    month: str = "",
    user_id: int = Depends(get_current_user),
):
    if not month:
        month = datetime.now().strftime("%Y-%m")

    validate_month(month)

    with get_db() as con:
        totals = con.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN kind = 'Income' THEN amount ELSE 0 END), 0) AS income,
                COALESCE(SUM(CASE WHEN kind = 'Expense' THEN amount ELSE 0 END), 0) AS expense
            FROM transactions
            WHERE user_id = ? AND substr(date, 1, 7) = ?
            """,
            (user_id, month),
        ).fetchone()

        categories = con.execute(
            """
            SELECT category, ROUND(SUM(amount), 2) AS total
            FROM transactions
            WHERE user_id = ?
                AND kind = 'Expense'
                AND substr(date, 1, 7) = ?
            GROUP BY category
            ORDER BY total DESC
            """,
            (user_id, month),
        ).fetchall()

        budget_row = con.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS total
            FROM budgets
            WHERE user_id = ? AND month = ?
            """,
            (user_id, month),
        ).fetchone()

    income = round(totals["income"], 2)
    expense = round(totals["expense"], 2)
    budget = round(budget_row["total"], 2)

    return {
        "month": month,
        "income": income,
        "expense": expense,
        "balance": round(income - expense, 2),
        "budget": budget,
        "budget_remaining": round(budget - expense, 2),
        "category_spending": [dict(row) for row in categories],
    }


@app.get("/api/reports/categories")
def category_report(
    month: str = "",
    user_id: int = Depends(get_current_user),
):
    if not month:
        month = datetime.now().strftime("%Y-%m")

    validate_month(month)

    with get_db() as con:
        rows = con.execute(
            """
            SELECT category, SUM(amount) AS total
            FROM transactions
            WHERE user_id = ?
                AND kind = 'Expense'
                AND substr(date, 1, 7) = ?
            GROUP BY category
            ORDER BY total DESC
            """,
            (user_id, month),
        ).fetchall()

    return {"month": month, "categories": [dict(row) for row in rows]}
