import mysql.connector
from mysql.connector import Error
import os

def get_db_connection(database=None):
    """Establishes a connection to the MySQL database."""
    # Use default DB name if not provided, unless explicitly set to None (to check connection/create DB)
    if database is None:
        database = os.environ.get('DB_NAME', 'gene_app')

    try:
        # Try connecting with the specified database
        connection = mysql.connector.connect(
            host=os.environ.get('DB_HOST', 'localhost'),
            port=int(os.environ.get('DB_PORT', 3306)),
            user=os.environ.get('DB_USER', 'root'),
            password=os.environ.get('DB_PASSWORD', '2005'),
            database=database
        )
        if connection.is_connected():
            return connection
    except Error as e:
        # If database unknown, try connecting without it to create it later
        if e.errno == 1049: # Unknown database
             try:
                 connection = mysql.connector.connect(
                    host=os.environ.get('DB_HOST', 'localhost'),
                    port=int(os.environ.get('DB_PORT', 3306)),
                    user=os.environ.get('DB_USER', 'root'),
                    password=os.environ.get('DB_PASSWORD', '2005')
                )
                 return connection
             except Error as ex:
                 print(f"Error connecting without DB: {ex}")
                 return None

        print(f"Error while connecting to MySQL: {e}")
        return None

def get_user_by_email(email):
    """Fetches a user by email from the database."""
    connection = get_db_connection()
    if connection is None:
        return None

    try:
        cursor = connection.cursor(dictionary=True)
        query = "SELECT * FROM users WHERE email = %s"
        cursor.execute(query, (email,))
        user = cursor.fetchone()
        return user
    except Error as e:
        if e.errno == 1046: # No database selected (shouldn't happen if get_db_connection logic holds, but safe guard)
             print("Database not selected/exists.")
        else:
             print(f"Error executing query: {e}")
        return None
        if connection.is_connected():
            cursor.close()
            connection.close()

def update_user_session_token(email, token):
    """Updates the session token for a user."""
    connection = get_db_connection()
    if connection is None:
        return False

    try:
        cursor = connection.cursor()
        query = "UPDATE users SET session_token = %s WHERE email = %s"
        cursor.execute(query, (token, email))
        connection.commit()
        return True
    except Error as e:
        print(f"Error updating session token: {e}")
        return False
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

def init_db():
    """Initializes the database and users table."""
    target_db = os.environ.get('DB_NAME', 'gene_app')
    
    # First, connect without specifying a DB to ensure it exists
    try:
        connection = mysql.connector.connect(
            host=os.environ.get('DB_HOST', 'localhost'),
            port=int(os.environ.get('DB_PORT', 3306)),
            user=os.environ.get('DB_USER', 'root'),
            password=os.environ.get('DB_PASSWORD', '2005')
        )
    except Error as e:
        print(f"Could not connect to MySQL server: {e}")
        return

    try:
        cursor = connection.cursor()
        # Create Database
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {target_db}")
        print(f"Database '{target_db}' checked/created.")
        
        # Switch to the database
        cursor.execute(f"USE {target_db}")
        
        # Create Table
        create_table_query = """
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            email VARCHAR(255) NOT NULL UNIQUE,
            password VARCHAR(255) NOT NULL,
            name VARCHAR(255),
            role VARCHAR(50) DEFAULT 'user'
        );
        """
        cursor.execute(create_table_query)
        connection.commit()
        print("Users table checked/created successfully.")
        
        # Create Pipeline Runs Table
        create_runs_table_query = """
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            run_id VARCHAR(50) PRIMARY KEY,
            user_email VARCHAR(255) NOT NULL,
            status VARCHAR(255) NOT NULL,
            start_time DATETIME DEFAULT CURRENT_TIMESTAMP,
            end_time DATETIME,
            FOREIGN KEY (user_email) REFERENCES users(email) ON DELETE CASCADE
        );
        """
        cursor.execute(create_runs_table_query)
        print("Pipeline runs table checked/created successfully.")
        
        # MIGRATION: Ensure session_token column exists
        try:
            cursor.execute("SELECT session_token FROM users LIMIT 1")
            cursor.fetchone() # Consume result to avoid UnreadResultError
        except Error:
            print("Migrating: Adding 'session_token' column...")
            cursor.execute("ALTER TABLE users ADD COLUMN session_token VARCHAR(255) DEFAULT NULL")
            connection.commit()
            print("Migration successful.")

    except Error as e:
        print(f"Error initializing database: {e}")
    
    # MIGRATION 2: Fix status column length (Fixes 'Data truncated' error)
    try:
        cursor.execute("ALTER TABLE pipeline_runs MODIFY COLUMN status VARCHAR(255)")
        connection.commit()
        print("Migration: status column updated to VARCHAR(255)")
    except Error as e:
        print(f"Migration warning (status): {e}")

    # MIGRATION 3: Add run_type column
    try:
        cursor.execute("SELECT run_type FROM pipeline_runs LIMIT 1")
        cursor.fetchone()
    except Error:
        print("Migrating: Adding 'run_type' column...")
        cursor.execute("ALTER TABLE pipeline_runs ADD COLUMN run_type VARCHAR(50) DEFAULT 'pipeline'")
        connection.commit()
        print("Migration successful.")

    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

def get_run_by_id(run_id):
    """Fetches a pipeline run by run_id from the database."""
    connection = get_db_connection()
    if connection is None:
        return None

    try:
        cursor = connection.cursor(dictionary=True)
        query = "SELECT * FROM pipeline_runs WHERE run_id = %s"
        cursor.execute(query, (run_id,))
        run = cursor.fetchone()
        return run
    except Error as e:
        print(f"Error executing query: {e}")
        return None
    finally:
        if connection and connection.is_connected():
            cursor.close()
            connection.close()
