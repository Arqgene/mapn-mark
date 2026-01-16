import mysql.connector
from models.db import get_db_connection, init_db
import sys
from dotenv import load_dotenv

load_dotenv()

def create_user(email, password, name, role='user', username=None, institution_id=None):
    conn = get_db_connection()
    if not conn:
        print("Failed to connect to database.")
        return

    try:
        cursor = conn.cursor()
        
        # Check if user exists
        check_query = "SELECT * FROM users WHERE email = %s OR username = %s"
        cursor.execute(check_query, (email, username))
        if cursor.fetchone():
            print(f"User with email {email} or username {username} already exists.")
            return
        
        # Validate Institution if provided
        if institution_id:
             cursor.execute("SELECT id FROM institutions WHERE id = %s", (institution_id,))
             if not cursor.fetchone():
                 print(f"Institution ID {institution_id} not found.")
                 return

        # Insert new user
        query = "INSERT INTO users (email, password, name, role, username, institution_id) VALUES (%s, %s, %s, %s, %s, %s)"
        cursor.execute(query, (email, password, name, role, username, institution_id))
        conn.commit()
        print(f"User '{name}' ({email}) created successfully with role '{role}'.")
        
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
    if len(sys.argv) >= 5:
        # python create_user.py email pass name role [username] [institution_id]
        email = sys.argv[1]
        password = sys.argv[2]
        name = sys.argv[3]
        role = sys.argv[4]
        username = sys.argv[5] if len(sys.argv) > 5 else email.split('@')[0]
        inst_id = sys.argv[6] if len(sys.argv) > 6 else None
        
        create_user(email, password, name, role, username, inst_id)
    else:
        # Interactive mode
        email = input("Email: ").strip()
        password = input("Password: ").strip()
        name = input("Name: ").strip()
        role = 'super_admin'
        username = input(f"Username [{email.split('@')[0]}]: ").strip() or email.split('@')[0]
        
        institution_id = None
        if role != 'super_admin':
            # List institutions helps
            conn = get_db_connection()
            if conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("SELECT id, name FROM institutions")
                insts = cursor.fetchall()
                if insts:
                    print("\nAvailable Institutions:")
                    for i in insts:
                        print(f"[{i['id']}] {i['name']}")
                    inst_input = input("Institution ID: ").strip()
                    if inst_input:
                        institution_id = int(inst_input)
                else:
                    print("\nNo institutions found. Create one first via API or DB.")
                conn.close()
        
        if email and password and name:
            create_user(email, password, name, role, username, institution_id)
        else:
            print("All fields are required.")
