import mysql.connector
from mysql.connector import Error
import os
import re


# -------------------------------------------------
# Database Connection
# -------------------------------------------------
def get_db_connection(database=None):
    if database is None:
        database = os.environ.get("DB_NAME", "gene_app")

    try:
        conn = mysql.connector.connect(
            host=os.environ.get("DB_HOST", "localhost"),
            port=int(os.environ.get("DB_PORT", 3306)),
            user=os.environ.get("DB_USER", "root"),
            password=os.environ.get("DB_PASSWORD"),
            database=database,
            autocommit=False
        )
        return conn

    except Error as e:
        if e.errno == 1049:  # Unknown database
            try:
                return mysql.connector.connect(
                    host=os.environ.get("DB_HOST", "localhost"),
                    port=int(os.environ.get("DB_PORT", 3306)),
                    user=os.environ.get("DB_USER", "root"),
                    password=os.environ.get("DB_PASSWORD"),
                    autocommit=False
                )
            except Error as ex:
                print(f"Error connecting without DB: {ex}")
                return None

        print(f"MySQL connection error: {e}")
        return None


# -------------------------------------------------
# Users
# -------------------------------------------------
def get_user_by_email(email):
    conn = get_db_connection()
    if not conn:
        return None

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        return cursor.fetchone()
    except Error as e:
        print(f"Query error: {e}")
        return None
    finally:
        cursor.close()
        conn.close()


def update_user_session_token(email, token):
    conn = get_db_connection()
    if not conn:
        return False

    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET session_token = %s WHERE email = %s",
            (token, email)
        )
        conn.commit()
        return True
    except Error as e:
        print(f"Session update error: {e}")
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()


# -------------------------------------------------
# Database Initialization & Migrations
# -------------------------------------------------
def init_db():
    db_name = os.environ.get("DB_NAME", "gene_app")

    if not re.match(r"^[a-zA-Z0-9_]+$", db_name):
        raise ValueError("Invalid DB_NAME")

    conn = get_db_connection(database=None)
    if not conn:
        return

    try:
        cursor = conn.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}`")
        cursor.execute(f"USE `{db_name}`")

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS institutions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(255) NOT NULL UNIQUE,
            user_limit INT DEFAULT 10,
            admin_limit INT DEFAULT 1,
            license_expiry DATE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            email VARCHAR(255) NOT NULL UNIQUE,
            username VARCHAR(255) UNIQUE,
            password VARCHAR(255) NOT NULL,
            name VARCHAR(255),
            role VARCHAR(50) DEFAULT 'user',
            institution_id INT,
            session_token VARCHAR(255),
            FOREIGN KEY (institution_id)
                REFERENCES institutions(id)
                ON DELETE SET NULL
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            run_id VARCHAR(50) PRIMARY KEY,
            user_email VARCHAR(255) NOT NULL,
            status VARCHAR(255),
            start_time DATETIME DEFAULT CURRENT_TIMESTAMP,
            end_time DATETIME,
            run_type VARCHAR(50) DEFAULT 'pipeline',
            FOREIGN KEY (user_email)
                REFERENCES users(email)
                ON DELETE CASCADE
        )
        """)

        conn.commit()

    except Error as e:
        print(f"DB init error: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()


# -------------------------------------------------
# Institutions
# -------------------------------------------------
def get_institutions():
    conn = get_db_connection()
    if not conn:
        return []

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM institutions")
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def create_institution(name, user_limit=10, admin_limit=1):
    conn = get_db_connection()
    if not conn:
        return False

    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO institutions (name, user_limit, admin_limit) VALUES (%s, %s, %s)",
            (name, user_limit, admin_limit)
        )
        conn.commit()
        return True
    except Error as e:
        print(f"Institution create error: {e}")
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()


def get_users_by_institution_id(inst_id):
    conn = get_db_connection()
    if not conn:
        return []

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, name, email, role, username, institution_id FROM users WHERE institution_id = %s",
            (inst_id,)
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


# -------------------------------------------------
# Pipeline Runs
# -------------------------------------------------
def get_run_by_id(run_id):
    conn = get_db_connection()
    if not conn:
        return None

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM pipeline_runs WHERE run_id = %s",
            (run_id,)
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()
