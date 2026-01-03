import mysql.connector
from models.db import get_db_connection, init_db
import sys
from dotenv import load_dotenv

load_dotenv()

def create_user(email, password, name, role='user'):
    conn = get_db_connection()
    if not conn:
        print("Failed to connect to database.")
        return

    try:
        cursor = conn.cursor()
        
        # Check if user exists
        check_query = "SELECT * FROM users WHERE email = %s"
        cursor.execute(check_query, (email,))
        if cursor.fetchone():
            print(f"User with email {email} already exists.")
            return

        # Insert new user
        query = "INSERT INTO users (email, password, name, role) VALUES (%s, %s, %s, %s)"
        cursor.execute(query, (email, password, name, role))
        conn.commit()
        print(f"User '{name}' ({email}) created successfully.")
        
    except mysql.connector.Error as e:
        print(f"Error creating user: {e}")
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()

if __name__ == "__main__":
    # Ensure DB exists
    init_db()

    print("--- Create New User ---")
    if len(sys.argv) == 5:
        # creating from command line args: python create_user.py email pass name role
        create_user(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        # Interactive mode
        email = input("Email: ").strip()
        password = input("Password: ").strip()
        name = input("Name: ").strip()
        role = input("Role (user/admin) [user]: ").strip() or "user"
        
        if email and password and name:
            create_user(email, password, name, role)
        else:
            print("All fields are required.")
