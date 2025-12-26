#!/usr/bin/env python3
"""
Database connection test script for AuthGuard with NeonDB
Run this after setting up your DATABASE_URL in .env file
"""

import os
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

def test_connection():
    load_dotenv()
    DATABASE_URL = os.getenv('DATABASE_URL')

    if not DATABASE_URL:
        print("❌ DATABASE_URL not found in .env file")
        return False

    try:
        print("🔄 Testing connection to NeonDB...")
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        cursor = conn.cursor()

        # Test query
        cursor.execute("SELECT version()")
        version = cursor.fetchone()
        print("✅ Connected successfully!")
        print(f"📊 PostgreSQL version: {version['version']}")

        # Test table creation
        print("🔄 Creating tables...")
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                username VARCHAR(255) PRIMARY KEY,
                password_hash TEXT NOT NULL,
                role VARCHAR(50) DEFAULT 'customer',
                flight_mean REAL DEFAULT 0.0,
                dwell_mean REAL DEFAULT 0.0,
                mouse_mean REAL DEFAULT 0.0,
                scroll_mean INTEGER DEFAULT 0,
                scroll_speed REAL DEFAULT 0.0,
                touch_mean REAL DEFAULT 0.0,
                fraud INTEGER DEFAULT 0,
                status VARCHAR(50) DEFAULT 'Registered',
                last_update BIGINT DEFAULT 0,
                locked_until BIGINT DEFAULT 0
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_history (
                id SERIAL PRIMARY KEY,
                username VARCHAR(255) REFERENCES users(username),
                ts BIGINT NOT NULL,
                flight REAL,
                dwell REAL,
                mouse_speed REAL,
                mouse_metrics JSONB,
                touch_speed REAL,
                touch_metrics JSONB,
                click_positions JSONB,
                scrolls INTEGER,
                scroll_speed REAL,
                scroll_speeds JSONB,
                clicks INTEGER,
                fraud INTEGER,
                status VARCHAR(50)
            )
        ''')

        conn.commit()
        print("✅ Tables created successfully!")

        cursor.close()
        conn.close()
        print("🎉 Database setup complete!")
        return True

    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return False

if __name__ == "__main__":
    test_connection()