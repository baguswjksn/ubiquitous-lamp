from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash, g
import sqlite3
import json
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os

app = Flask(__name__)

# Secret key for session cookies — set via environment in production
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key")  # change in production

DB_NAME = "library.db"

def get_db():
    # simple connection helper; reuse via flask.g if desirable
    if hasattr(g, "sqlite_db"):
        return g.sqlite_db
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    g.sqlite_db = conn
    return conn

@app.teardown_appcontext
def close_db(error):
    if hasattr(g, "sqlite_db"):
        g.sqlite_db.close()

# ---------- User / Auth helpers ----------
def init_db():
    """
    Create the users table if it doesn't exist. Safe to run multiple times.
    """
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()

def create_user(username: str, password: str, is_admin: bool = False) -> bool:
    """
    Insert a new user with a hashed password. Returns True on success.
    """
    password_hash = generate_password_hash(password)
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)",
            (username, password_hash, 1 if is_admin else 0)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def get_user_by_username(username: str):
    conn = get_db()
    cur = conn.cursor()
    return cur.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

def get_user_by_id(user_id: int):
    conn = get_db()
    cur = conn.cursor()
    return cur.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

# Simple login-required decorator (optional if you use before_request approach)
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return decorated

# Enforce login for most endpoints (except the exempted ones)
@app.before_request
def require_login():
    # endpoints that don't require login
    exempt_endpoints = ("login", "logout", "static")
    if request.endpoint:
        endpoint_name = request.endpoint.split(".")[-1]
        if endpoint_name in exempt_endpoints:
            return
    if not session.get("user_id"):
        return redirect(url_for("login", next=request.path))

# ---------------- Authentication routes ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    # If already logged in, redirect to dashboard
    if session.get("user_id"):
        return redirect(url_for("dashboard"))

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = get_user_by_username(username)
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["is_admin"] = bool(user["is_admin"])
            next_page = request.args.get("next") or url_for("dashboard")
            return redirect(next_page)
        else:
            error = "Invalid username or password"
            flash(error, "error")

    return render_template("auth/login.html", error=error)

@app.route("/logout")
def logout():
    session.pop("user_id", None)
    session.pop("username", None)
    session.pop("is_admin", None)
    return redirect(url_for("login"))

# ---------------- DASHBOARD ----------------
@app.route("/")
def dashboard():
    conn = get_db()
    cur = conn.cursor()

    # Counts
    book_count = cur.execute("SELECT COUNT(*) FROM books WHERE deleted = 0").fetchone()[0]
    quote_count = cur.execute("SELECT COUNT(*) FROM quotes WHERE is_deleted = 0").fetchone()[0]
    author_count = cur.execute("SELECT COUNT(*) FROM authors WHERE is_deleted = 0").fetchone()[0]

    # Recent books
    books = cur.execute(
        """
        SELECT
            books.id,
            books.title,
            books.format,
            books.status,
            authors.id AS author_id,
            authors.name AS author_name
        FROM books
        JOIN authors ON books.author_id = authors.id
        WHERE books.deleted = 0
        ORDER BY books.id DESC
        LIMIT 5
        """
    ).fetchall()

    # Most recent quote
    quote = cur.execute(
        """
        SELECT
            quotes.content,
            books.title AS book_title
        FROM quotes
        LEFT JOIN books ON quotes.book_id = books.id
        WHERE quotes.is_deleted = 0
        ORDER BY quotes.created_at DESC
        LIMIT 1
        """
    ).fetchone()

    conn.close()

    return render_template(
        "dashboard.html",
        book_count=book_count,
        quote_count=quote_count,
        author_count=author_count,
        books=books,
        quote=quote
    )

# ---------------- BOOKS ----------------
@app.route("/books")
def books():
    search = request.args.get("q", "")

    conn = get_db()
    cur = conn.cursor()

    if search:
        books = cur.execute(
            """
            SELECT books.*, authors.name AS author_name
            FROM books
            JOIN authors ON books.author_id = authors.id
            WHERE books.deleted = 0
            AND (books.title LIKE ? OR authors.name LIKE ?)
            ORDER BY books.id DESC
            """,
            (f"%{search}%", f"%{search}%")
        ).fetchall()
    else:
        books = cur.execute(
            """
            SELECT books.*, authors.name AS author_name
            FROM books
            JOIN authors ON books.author_id = authors.id
            WHERE books.deleted = 0
            ORDER BY books.id DESC
            """
        ).fetchall()


    conn.close()
    return render_template("book/list.html", books=books, search=search)

@app.route("/books/add", methods=["GET", "POST"])
def add_book():
    conn = get_db()
    cur = conn.cursor()

    if request.method == "POST":
        title = request.form["title"]
        author_name = request.form["author"]
        format_ = request.form["format"]
        status = request.form["status"]
        total_pages = request.form.get("total_pages")
        current_page = request.form.get("current_page", 0)

        # Get or create author
        cur.execute(
            "SELECT id FROM authors WHERE name = ?",
            (author_name,)
        )
        author = cur.fetchone()

        if author is None:
            cur.execute(
                "INSERT INTO authors (name) VALUES (?)",
                (author_name,)
            )
            author_id = cur.lastrowid
        else:
            author_id = author["id"]

        cur.execute(
            """
            INSERT INTO books (
                title, author_id, format, status, total_pages, current_page
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (title, author_id, format_, status, total_pages, current_page)
        )

        conn.commit()
        conn.close()
        return redirect(url_for("books"))

    authors = conn.execute(
        "SELECT name FROM authors ORDER BY name"
    ).fetchall()
    conn.close()

    return render_template("book/form.html", book=None, authors=authors)

@app.route("/books/edit/<int:book_id>", methods=["GET", "POST"])
def edit_book(book_id):
    conn = get_db()
    cur = conn.cursor()

    if request.method == "POST":
        title = request.form["title"]
        author_name = request.form["author"]
        format_ = request.form["format"]
        status = request.form["status"]
        total_pages = request.form.get("total_pages")
        current_page = request.form.get("current_page", 0)

        # Get or create author
        cur.execute(
            "SELECT id FROM authors WHERE name = ?",
            (author_name,)
        )
        author = cur.fetchone()

        if author is None:
            cur.execute(
                "INSERT INTO authors (name) VALUES (?)",
                (author_name,)
            )
            author_id = cur.lastrowid
        else:
            author_id = author["id"]

        cur.execute(
            """
            UPDATE books
            SET title = ?,
                author_id = ?,
                format = ?,
                status = ?,
                total_pages = ?,
                current_page = ?
            WHERE id = ?
            """,
            (
                title,
                author_id,
                format_,
                status,
                total_pages,
                current_page,
                book_id
            )
        )

        conn.commit()
        conn.close()
        return redirect(url_for("books"))

    # GET — fetch book + author name
    book = cur.execute(
        """
        SELECT
            books.*,
            authors.name AS author_name
        FROM books
        JOIN authors ON books.author_id = authors.id
        WHERE books.id = ?
        """,
        (book_id,)
    ).fetchone()

    authors = conn.execute(
        "SELECT name FROM authors ORDER BY name"
    ).fetchall()

    conn.close()

    return render_template("book/form.html", book=book, authors=authors)

@app.route("/books/view/<int:book_id>")
def view_book(book_id):
    conn = get_db()
    cur = conn.cursor()

    # Fetch book details
    book_row = cur.execute(
        """
        SELECT books.*, authors.name AS author_name
        FROM books
        JOIN authors ON books.author_id = authors.id
        WHERE books.id = ? AND books.deleted = 0
        """,
        (book_id,)
    ).fetchone()

    if not book_row:
        conn.close()
        return "Book not found or deleted", 404

    # Convert book_row to a dict
    book = dict(book_row)

    # Fetch all quotes for this book
    quotes_rows = cur.execute(
        "SELECT * FROM quotes WHERE book_id = ? AND is_deleted = 0 ORDER BY id ASC",
        (book_id,)
    ).fetchall()

    # Convert each quote row to a dict
    quotes = [dict(q) for q in quotes_rows]

    conn.close()

    # Now quotes and book are fully JSON serializable
    return render_template("book/view.html", book=book, quotes=quotes)

@app.route("/books/delete/<int:book_id>")
def delete_book(book_id):
    conn = get_db()

    # Soft delete the book
    conn.execute(
        "UPDATE books SET deleted = 1 WHERE id = ?",
        (book_id,)
    )

    # Soft delete related quotes
    conn.execute(
        "UPDATE quotes SET is_deleted = 1 WHERE book_id = ?",
        (book_id,)
    )

    conn.commit()
    conn.close()
    return redirect(url_for("books"))

@app.route("/quotes")
def quotes():
    search = request.args.get("q", "")

    conn = get_db()
    cur = conn.cursor()

    if search:
        quotes = cur.execute(
            """
            SELECT quotes.*, books.title AS book_title
            FROM quotes
            JOIN books ON quotes.book_id = books.id
            WHERE quotes.content LIKE ? OR books.title LIKE ?
              AND books.deleted = 0
            ORDER BY quotes.id DESC
            """,
            (f"%{search}%", f"%{search}%")
        ).fetchall()
    else:
        quotes = cur.execute(
            """
            SELECT quotes.*, books.title AS book_title
            FROM quotes
            JOIN books ON quotes.book_id = books.id
            WHERE books.deleted = 0
            AND quotes.is_deleted = 0
            ORDER BY quotes.id DESC
            """
        ).fetchall()

    conn.close()
    return render_template("quote/list.html", quotes=quotes, search=search)

@app.route("/quotes/add", methods=["GET", "POST"])
def add_quote():
    conn = get_db()
    cur = conn.cursor()

    # Fetch only active books
    books = cur.execute(
        "SELECT id, title, total_pages FROM books WHERE deleted = 0 ORDER BY title"
    ).fetchall()

    if request.method == "POST":
        book_id = request.form["book_id"]
        content = request.form["content"]
        page_number = request.form.get("page_number")

        # Convert page_number to int if not empty
        page_number = int(page_number) if page_number else None

        # Get total_pages for the selected book
        total_pages = cur.execute(
            "SELECT total_pages FROM books WHERE id = ?", (book_id,)
        ).fetchone()["total_pages"]

        # Validate page_number
        if page_number is not None and page_number > total_pages:
            conn.close()
            return f"Error: Page number {page_number} exceeds total pages ({total_pages}) of the book.", 400

        cur.execute(
            "INSERT INTO quotes (book_id, content, page_number) VALUES (?, ?, ?)",
            (book_id, content, page_number)
        )
        conn.commit()
        conn.close()
        return redirect(url_for("quotes"))

    conn.close()
    return render_template("quote/form.html", quote=None, books=books)

@app.route("/quotes/edit/<int:quote_id>", methods=["GET", "POST"])
def edit_quote(quote_id):
    conn = get_db()
    cur = conn.cursor()

    # Get books for dropdown
    books = cur.execute("SELECT id, title, total_pages FROM books WHERE deleted = 0 ORDER BY title").fetchall()

    if request.method == "POST":
        book_id = request.form["book_id"]
        content = request.form["content"]
        page_number = request.form.get("page_number")

        page_number = int(page_number) if page_number else None

        # Validate page_number
        total_pages = cur.execute(
            "SELECT total_pages FROM books WHERE id = ?", (book_id,)
        ).fetchone()["total_pages"]

        if page_number is not None and page_number > total_pages:
            conn.close()
            return f"Error: Page number {page_number} exceeds total pages ({total_pages}) of the book.", 400

        cur.execute(
            "UPDATE quotes SET book_id = ?, content = ?, page_number = ? WHERE id = ?",
            (book_id, content, page_number, quote_id)
        )
        conn.commit()
        conn.close()
        return redirect(url_for("quotes"))

    # Fetch quote with book info
    quote = cur.execute(
        "SELECT * FROM quotes WHERE id = ?", (quote_id,)
    ).fetchone()

    conn.close()
    return render_template("quote/form.html", quote=quote, books=books)

@app.route("/quotes/delete/<int:quote_id>")
def delete_quote(quote_id):
    conn = get_db()
    conn.execute("UPDATE quotes SET is_deleted = 1 WHERE id = ?", (quote_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("quotes"))

@app.route("/authors")
def authors():
    conn = get_db()
    cur = conn.cursor()

    search_query = request.args.get('q', '')  # get search term from URL, default is empty
    if search_query:
        authors_list = cur.execute(
            "SELECT * FROM authors WHERE is_deleted=0 AND name LIKE ? ORDER BY name",
            (f"%{search_query}%",)
        ).fetchall()
    else:
        authors_list = cur.execute(
            "SELECT * FROM authors WHERE is_deleted=0 ORDER BY name"
        ).fetchall()

    conn.close()
    return render_template("author/list.html", authors=authors_list, search_query=search_query)


@app.route("/authors/add", methods=["GET", "POST"])
def add_author():
    if request.method == "POST":
        name = request.form["name"].strip()
        if not name:
            return redirect(url_for("add_author"))

        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO authors (name) VALUES (?)",
                (name,)
            )
            conn.commit()
        except sqlite3.IntegrityError:
            pass
        finally:
            conn.close()

        return redirect(url_for("authors"))

    return render_template("author/form.html", author=None)

@app.route("/authors/edit/<int:author_id>", methods=["GET", "POST"])
def edit_author(author_id):
    conn = get_db()
    cur = conn.cursor()
    author = cur.execute(
        "SELECT * FROM authors WHERE id = ? AND is_deleted = 0",
        (author_id,)
    ).fetchone()

    if not author:
        flash("Author not found.", "error")
        conn.close()
        return redirect(url_for("authors"))

    if request.method == "POST":
        new_name = request.form["name"].strip()
        if not new_name:
            conn.close()
            return redirect(url_for("edit_author", author_id=author_id))

        try:
            conn.execute(
                "UPDATE authors SET name = ? WHERE id = ?",
                (new_name, author_id)
            )
            conn.commit()
        except sqlite3.IntegrityError:
            pass
        finally:
            conn.close()

        return redirect(url_for("authors"))

    conn.close()
    return render_template("author/form.html", author=author)


@app.route("/authors/delete/<int:author_id>", methods=["POST"])
def delete_author(author_id):
    conn = get_db()
    cursor = conn.cursor()

    # Soft delete author
    cursor.execute(
        "UPDATE authors SET is_deleted = 1 WHERE id = ?",
        (author_id,)
    )

    # Soft delete books by author
    cursor.execute(
        "UPDATE books SET deleted = 1 WHERE author_id = ?",
        (author_id,)
    )

    # Soft delete quotes for books by author
    cursor.execute(
        """
        UPDATE quotes
        SET is_deleted = 1
        WHERE book_id IN (
            SELECT id FROM books WHERE author_id = ?
        )
        """,
        (author_id,)
    )

    conn.commit()
    conn.close()

    return redirect(url_for("authors"))


@app.route("/authors/<int:author_id>")
def author_detail(author_id):
    conn = get_db()
    cur = conn.cursor()

    # Get author info
    author = cur.execute("SELECT * FROM authors WHERE id = ? AND is_deleted=0", (author_id,)).fetchone()
    if not author:
        flash("Author not found.", "error")
        return redirect(url_for("authors"))

    # Get author's books
    books = cur.execute("""
        SELECT *
        FROM books
        WHERE author_id = ? AND deleted = 0
        ORDER BY title
    """, (author_id,)).fetchall()

    # Get quotes from author's books
    quotes = cur.execute("""
        SELECT quotes.content, quotes.page_number, books.title AS book_title
        FROM quotes
        JOIN books ON quotes.book_id = books.id
        WHERE books.author_id = ? AND quotes.is_deleted = 0
        ORDER BY quotes.created_at DESC
    """, (author_id,)).fetchall()

    conn.close()
    return render_template("author/view.html", author=author, books=books, quotes=quotes)

if __name__ == "__main__":
    import argparse
    import getpass

    parser = argparse.ArgumentParser(description="Run the Flask app or perform user/db tasks.")
    parser.add_argument("command", nargs="?", choices=["run", "init-db", "create-user"], default="run",
                        help="Command to run: 'run' starts the server, 'init-db' creates the users table, 'create-user' creates a user.")
    parser.add_argument("--username", "-u", help="Username for create-user")
    parser.add_argument("--password", "-p", help="Password for create-user (omit to be prompted)")
    parser.add_argument("--admin", action="store_true", help="Create user as admin")
    parser.add_argument("--host", default="127.0.0.1", help="Host for run")
    parser.add_argument("--port", type=int, default=5000, help="Port for run")
    args = parser.parse_args()

    if args.command == "init-db":
        init_db()
        print("Initialized database (ensured users table exists).")
    elif args.command == "create-user":
        init_db()  # ensure table exists
        username = args.username
        if not username:
            username = input("Username: ").strip()
        password = args.password
        if not password:
            password = getpass.getpass("Password: ")
            password_confirm = getpass.getpass("Confirm Password: ")
            if password != password_confirm:
                print("Passwords do not match.")
                raise SystemExit(1)
        success = create_user(username, password, is_admin=args.admin)
        if success:
            print(f"User '{username}' created.")
        else:
            print(f"Failed to create user '{username}' — it may already exist.")
    else:
        # run the app
        # ensure DB exists with users table (no-op if already created)
        init_db()
        app.run(host=args.host, port=args.port, debug=True)