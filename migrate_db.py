import mysql.connector
import os
from dotenv import load_dotenv

load_dotenv()

def add_session_column():
    print("--- Migrating Database Schema ---")
    try:
        conn = mysql.connector.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", 3306)),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASSWORD", "2005"),
            database=os.getenv("DB_NAME", "gene_app")
        )
        cursor = conn.cursor()
        
        # Check if column exists
        cursor.execute("SHOW COLUMNS FROM users LIKE 'session_token'")
        result = cursor.fetchone()
        
        if not result:
            print("Adding 'session_token' column...")
            cursor.execute("ALTER TABLE users ADD COLUMN session_token VARCHAR(255) DEFAULT NULL")
            conn.commit()
            print("Migration successful: Column added.")
        else:
            print("Column 'session_token' already exists. No changes needed.")
            
        conn.close()
    except Exception as e:
        print(f"Migration Failed: {e}")

if __name__ == "__main__":
    add_session_column()
