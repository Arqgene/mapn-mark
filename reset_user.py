
import os
import sys
from models.db import get_db_connection

email = "smp@gmail.com"
password = "2005"
name = "SMP User"

conn = get_db_connection()
if conn:
    cursor = conn.cursor()
    try:
        print(f"Deleting user {email}...")
        cursor.execute("DELETE FROM users WHERE email = %s", (email,))
        conn.commit()
        print(f"Deleted {cursor.rowcount} user(s).")

        print(f"Recreating user {email}...")
        cursor.execute("INSERT INTO users (email, password, name) VALUES (%s, %s, %s)", (email, password, name))
        conn.commit()
        print(f"User recreated successfully. Password: {password}")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        cursor.close()
        conn.close()
else:
    print("Could not connect to DB")
