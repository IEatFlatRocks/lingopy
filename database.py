import sqlite3

def init_db():
    conn = sqlite3.connect('library.db')
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            youtube_id TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            filename TEXT NOT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS subtitles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER,
            lang_code TEXT NOT NULL,
            lang_name TEXT NOT NULL,
            filename TEXT NOT NULL,
            FOREIGN KEY (video_id) REFERENCES videos (id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vocabulary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT NOT NULL UNIQUE,
            definition TEXT NOT NULL,
            context TEXT NOT NULL
        )
    ''')

    print("Database initialized successfully.")
    conn.commit()
    conn.close()

if __name__ == '__main__':
    init_db()