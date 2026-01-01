import sqlite3
from pathlib import Path

DB_NAME = "library.db"


def create_tables(conn):
    cur = conn.cursor()

    cur.executescript("""
CREATE TABLE IF NOT EXISTS authors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    is_deleted INTEGER DEFAULT 0
);

-- Table for books
CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    author_id INTEGER NOT NULL,
    format TEXT,
    status TEXT,
    published_year INTEGER,
    genre TEXT,
    total_pages INTEGER,
    current_page INTEGER DEFAULT 0,
    deleted INTEGER DEFAULT 0,      -- 0 = active, 1 = deleted
    FOREIGN KEY (author_id) REFERENCES authors(id) ON DELETE CASCADE
);

-- Table for quotes
CREATE TABLE IF NOT EXISTS quotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER,
    content TEXT NOT NULL,
    page_number INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_deleted INTEGER DEFAULT 0,  -- 0 = not deleted, 1 = deleted
    FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
);

-- Optional table for citations
CREATE TABLE IF NOT EXISTS citations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER,
    quote_id INTEGER,
    citation_text TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
    FOREIGN KEY (quote_id) REFERENCES quotes(id) ON DELETE CASCADE
);
    """)
    conn.commit()

def insert_dummy_data(conn):
    cur = conn.cursor()

    # 1. Insert authors
    authors = [
        "Andrew Hunt",
        "Robert C. Martin",
        "Marcus Aurelius",
        "Cal Newport",
        "James Clear",
    ]

    for author in authors:
        cur.execute(
            "INSERT OR IGNORE INTO authors (name) VALUES (?)",
            (author,)
        )

    # Helper: get author_id by name
    def get_author_id(name):
        cur.execute("SELECT id FROM authors WHERE name = ?", (name,))
        return cur.fetchone()[0]

    # 2. Insert books
    books = [
        ("The Pragmatic Programmer", "Andrew Hunt", "PDF", "Reading", 352, 120),
        ("Clean Architecture", "Robert C. Martin", "E-Book", "Unread", 432, 0),
        ("Meditations", "Marcus Aurelius", "Physical", "Completed", 304, 304),
        ("Deep Work", "Cal Newport", "E-Book", "Reading", 296, 87),
        ("Atomic Habits", "James Clear", "Audiobook", "Completed", 320, 320),
    ]

    for title, author_name, format_, status, total_pages, current_page in books:
        author_id = get_author_id(author_name)
        cur.execute(
            """
            INSERT INTO books (
                title, author_id, format, status, total_pages, current_page
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (title, author_id, format_, status, total_pages, current_page)
        )

    # Helper: get book_id by title
    def get_book_id(title):
        cur.execute("SELECT id FROM books WHERE title = ?", (title,))
        return cur.fetchone()[0]

    # 3. Insert quotes (FIXED)
    quotes = [
        ("Meditations", "You have power over your mind — not outside events.", 12),
        ("Deep Work", "Clarity about what matters provides clarity about what does not.", 45),
        ("Atomic Habits", "You do not rise to the level of your goals. You fall to the level of your systems.", 27),
    ]

    for book_title, content, page_number in quotes:
        book_id = get_book_id(book_title)
        cur.execute(
            """
            INSERT INTO quotes (book_id, content, page_number)
            VALUES (?, ?, ?)
            """,
            (book_id, content, page_number)
        )

    conn.commit()

def main():
    if Path(DB_NAME).exists():
        print(f"{DB_NAME} already exists. Delete it first if you want a fresh database.")
        return

    conn = sqlite3.connect(DB_NAME)
    create_tables(conn)
    insert_dummy_data(conn)
    conn.close()

    print("Database created and populated with dummy data.")

if __name__ == "__main__":
    main()
