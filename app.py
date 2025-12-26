# app.py - final backend: register/login/verify/admin/profiles with lockout
from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import os, json, numpy as np
from time import time
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app)

# Database configuration
DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set. Please check your .env file.")

ADMIN_SECRET = "ADMIN123"

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Create users table
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

    # Create history table
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
    cursor.close()
    conn.close()

# Initialize database on startup
init_db()

def safe_mean(arr):
    try:
        return float(np.mean(arr)) if arr and len(arr) else 0.0
    except:
        return 0.0

@app.route("/register", methods=["POST"])
def register():
    d = request.json or {}
    username = d.get("username")
    password = d.get("password")
    if not username or not password:
        return jsonify({"error":"username and password required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if user exists
    cursor.execute("SELECT username FROM users WHERE username = %s", (username,))
    if cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({"error":"user already exists"}), 400

    flight = d.get("flight", [])
    dwell = d.get("dwell", [])
    mouse_speed = d.get("mouse_speed", 0.0)
    scrolls = d.get("scrolls", 0)
    scroll_speed = d.get("scroll_speed", 0.0)
    touch_interactions = d.get("touch_interactions", 0)

    profile = {
        "flight_mean": round(safe_mean(flight), 2),
        "dwell_mean": round(safe_mean(dwell), 2),
        "mouse_mean": round(float(mouse_speed), 2),
        "scroll_mean": int(scrolls),
        "scroll_speed": round(float(scroll_speed), 2),
        "touch_mean": round(float(touch_interactions), 2)
    }

    # Insert user
    cursor.execute('''
        INSERT INTO users (username, password_hash, role, flight_mean, dwell_mean, mouse_mean,
                          scroll_mean, scroll_speed, touch_mean, status, last_update)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ''', (
        username,
        generate_password_hash(password),
        'customer',
        profile["flight_mean"],
        profile["dwell_mean"],
        profile["mouse_mean"],
        profile["scroll_mean"],
        profile["scroll_speed"],
        profile["touch_mean"],
        'Registered',
        int(time()*1000)
    ))

    # Insert initial history entry
    cursor.execute('''
        INSERT INTO user_history (username, ts, flight, dwell, mouse_speed, mouse_metrics,
                                touch_metrics, click_positions, scrolls, scroll_speed, clicks, fraud, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ''', (
        username,
        int(time()*1000),
        profile["flight_mean"],
        profile["dwell_mean"],
        profile["mouse_mean"],
        json.dumps({}),
        json.dumps({}),
        json.dumps([]),
        profile["scroll_mean"],
        profile["scroll_speed"],
        0,
        0,
        'Registered'
    ))

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"status":"registered","profile":profile})

@app.route("/login", methods=["POST"])
def login():
    d = request.json or {}
    username = d.get("username")
    password = d.get("password")
    role = d.get("role", "customer")
    secret = d.get("secret", "")

    conn = get_db_connection()
    cursor = conn.cursor()

    if role == "admin":
        if secret != ADMIN_SECRET:
            cursor.close()
            conn.close()
            return jsonify({"error":"invalid admin secret"}), 403

        # Check if admin exists, create if not
        cursor.execute("SELECT username FROM users WHERE username = %s", (username,))
        if not cursor.fetchone():
            cursor.execute('''
                INSERT INTO users (username, password_hash, role, status, last_update)
                VALUES (%s, %s, %s, %s, %s)
            ''', (username, generate_password_hash(password or ""), 'admin', 'Admin', int(time()*1000)))
        else:
            cursor.execute("UPDATE users SET role = %s WHERE username = %s", ('admin', username))

        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"status":"ok","role":"admin"})

    # Regular user login
    cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()

    if not user:
        return jsonify({"error":"user not found"}), 404

    now_ms = int(time()*1000)
    locked_until = user.get("locked_until", 0)
    if locked_until and locked_until > now_ms:
        return jsonify({"error":"locked","locked_until": locked_until}), 403

    if not user.get("password_hash") or not check_password_hash(user["password_hash"], password):
        return jsonify({"error":"invalid credentials"}), 403

    return jsonify({"status":"ok","role":user.get("role","customer")})

@app.route("/verify", methods=["POST"])
def verify():
    d = request.json or {}
    username = d.get("username", "default_user")
    initial = d.get("initial", False)
    ts = int(d.get("ts", time()*1000))

    conn = get_db_connection()
    cursor = conn.cursor()

    # Check lock status
    cursor.execute("SELECT locked_until, fraud FROM users WHERE username = %s", (username,))
    user_lock = cursor.fetchone()
    if user_lock and user_lock["locked_until"] and user_lock["locked_until"] > int(time()*1000):
        cursor.close()
        conn.close()
        return jsonify({"status":"Locked","fraud_score": user_lock["fraud"], "locked_until": user_lock["locked_until"]})

    # Parse incoming data
    flight = d.get("flight", []) or []
    dwell = d.get("dwell", []) or []
    mouse_speed = float(d.get("mouse_speed", 0.0) or 0.0)
    mouse_path = d.get("mouse_path", []) or []
    touch_speed = float(d.get("touch_speed", 0.0) or 0.0)
    touch_path = d.get("touch_path", []) or []
    click_positions = d.get("click_positions", []) or []
    clicks = int(d.get("clicks", 0) or 0)
    scrolls = int(d.get("scrolls", 0) or 0)
    scroll_speed = float(d.get("scroll_speed", 0.0) or 0.0)
    incoming_score = int(d.get("fraud_score", 0) or 0)

    f = safe_mean(flight)
    dw = safe_mean(dwell)

    # Get or create user profile
    cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
    user = cursor.fetchone()

    if not user:
        # Create new user profile
        cursor.execute('''
            INSERT INTO users (username, password_hash, role, flight_mean, dwell_mean, mouse_mean,
                              scroll_mean, scroll_speed, touch_mean, status, last_update)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (
            username,
            generate_password_hash(""),
            'customer',
            round(f, 2),
            round(dw, 2),
            round(mouse_speed, 2),
            scrolls,
            round(scroll_speed, 2),
            round(touch_speed, 2),
            'Profiled',
            ts
        ))
        profile = {
            "flight_mean": round(f, 2),
            "dwell_mean": round(dw, 2),
            "mouse_mean": round(mouse_speed, 2),
            "scroll_mean": scrolls,
            "scroll_speed": round(scroll_speed, 2),
            "touch_mean": round(touch_speed, 2)
        }
    else:
        profile = {
            "flight_mean": float(user["flight_mean"] or f or 1.0),
            "dwell_mean": float(user["dwell_mean"] or dw or 1.0),
            "mouse_mean": float(user["mouse_mean"] or mouse_speed or 1.0),
            "scroll_mean": int(user["scroll_mean"] or scrolls or 0),
            "scroll_speed": float(user["scroll_speed"] or scroll_speed or 0.0),
            "touch_mean": float(user["touch_mean"] or touch_speed or 0.0)
        }

    # Calculate deviations
    def perc_dev(a, b):
        try:
            if b == 0:
                return 0 if a == 0 else 100
            return abs((a-b)/b)*100
        except:
            return 100

    dev_f = perc_dev(f, profile["flight_mean"])
    dev_dw = perc_dev(dw, profile["dwell_mean"])
    dev_m = perc_dev(mouse_speed, profile["mouse_mean"])
    dev_s = perc_dev(scrolls, profile["scroll_mean"])
    dev_ss = perc_dev(scroll_speed, profile["scroll_speed"])
    dev_touch = perc_dev(touch_speed, profile["touch_mean"])

    # Calculate path metrics
    def path_metrics(path):
        try:
            if not path or len(path) < 2: return {}
            xs = np.array([p['x'] for p in path], dtype=float)
            ys = np.array([p['y'] for p in path], dtype=float)
            ts_arr = np.array([p['t'] for p in path], dtype=float)
            dx = np.diff(xs)
            dy = np.diff(ys)
            dts = np.diff(ts_arr)/1000.0
            dts[dts==0] = 0.001
            dists = np.hypot(dx,dy)
            speeds = dists / dts
            total = float(np.sum(dists))
            avg = float(np.mean(speeds)) if speeds.size else 0.0
            var = float(np.var(speeds)) if speeds.size else 0.0
            angles = np.arctan2(dy,dx)
            ang_diff = np.abs(np.diff(angles))
            ang_diff = np.minimum(ang_diff, 2*np.pi - ang_diff)
            changes = float(np.sum(ang_diff > (np.pi/6)))
            duration = float((ts_arr[-1] - ts_arr[0]) / 1000.0) if ts_arr.size else 1.0
            dir_changes = changes / max(duration, 1.0)
            bins = 12
            hist, _ = np.histogram(angles, bins=bins, range=(-np.pi, np.pi))
            probs = hist / (hist.sum() if hist.sum() else 1)
            entropy = float(-np.sum([p*np.log2(p) for p in probs if p>0])) if probs.size else 0.0
            return {
                "path_length": round(float(total), 2),
                "avg_speed": round(float(avg),2),
                "speed_var": round(float(var),2),
                "direction_changes_per_sec": round(float(dir_changes),2),
                "angular_entropy": round(float(entropy),2)
            }
        except:
            return {}

    mouse_metrics = path_metrics(mouse_path)
    touch_metrics = path_metrics(touch_path)

    # Calculate fraud score
    score = 0
    score += min(dev_f * 0.25, 40)
    score += min(dev_dw * 0.2, 30)
    score += min(dev_m * 0.15, 20)
    score += min(dev_s * 0.1, 10)
    score += min(dev_ss * 0.1, 10)
    score += min(dev_touch * 0.08, 8)

    if mouse_metrics and mouse_metrics.get("angular_entropy", 0) < 1.0:
        score += 5
    if touch_metrics and touch_metrics.get("angular_entropy", 0) < 1.0:
        score += 3

    score = score * 0.7 + incoming_score * 0.3
    score = int(round(min(score, 100)))

    lock_threshold = 60
    now_ms = int(time()*1000)

    if score > lock_threshold:
        # Lock user
        cursor.execute('''
            UPDATE users SET locked_until = %s, status = %s, fraud = %s, last_update = %s
            WHERE username = %s
        ''', (now_ms + (60 * 1000), 'Locked', score, ts, username))

        # Add history entry
        cursor.execute('''
            INSERT INTO user_history (username, ts, flight, dwell, mouse_speed, mouse_metrics,
                                    touch_speed, touch_metrics, click_positions, scrolls, scroll_speed,
                                    scroll_speeds, clicks, fraud, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (
            username, ts, round(f,2), round(dw,2), round(mouse_speed,2), json.dumps(mouse_metrics),
            round(touch_speed,2), json.dumps(touch_metrics), json.dumps(click_positions),
            scrolls, round(scroll_speed,2), json.dumps(d.get("scroll_speeds", [])),
            clicks, score, 'Locked'
        ))

        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"status":"Locked","fraud_score":score,"locked_until": now_ms + (60 * 1000)})

    # Normal update
    status = "Authenticated" if score < 40 else ("Suspicious" if score < 70 else "Fraud Detected")

    # Add history entry
    cursor.execute('''
        INSERT INTO user_history (username, ts, flight, dwell, mouse_speed, mouse_metrics,
                                touch_speed, touch_metrics, click_positions, scrolls, scroll_speed,
                                scroll_speeds, clicks, fraud, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ''', (
        username, ts, round(f,2), round(dw,2), round(mouse_speed,2), json.dumps(mouse_metrics),
        round(touch_speed,2), json.dumps(touch_metrics), json.dumps(click_positions),
        scrolls, round(scroll_speed,2), json.dumps(d.get("scroll_speeds", [])),
        clicks, score, status
    ))

    # Update user profile with exponential moving average
    alpha = 0.02
    new_flight = round((1-alpha)*profile["flight_mean"] + alpha * f, 2)
    new_dwell = round((1-alpha)*profile["dwell_mean"] + alpha * dw, 2)
    new_mouse = round((1-alpha)*profile["mouse_mean"] + alpha * mouse_speed, 2)
    new_scroll = int(round((1-alpha)*profile["scroll_mean"] + alpha * scrolls))
    new_scroll_speed = round((1-alpha)*profile["scroll_speed"] + alpha * scroll_speed, 2)
    new_touch = round((1-alpha)*profile["touch_mean"] + alpha * touch_speed, 2)

    cursor.execute('''
        UPDATE users SET flight_mean = %s, dwell_mean = %s, mouse_mean = %s, scroll_mean = %s,
                         scroll_speed = %s, touch_mean = %s, fraud = %s, status = %s, last_update = %s
        WHERE username = %s
    ''', (
        new_flight, new_dwell, new_mouse, new_scroll, new_scroll_speed, new_touch,
        score, status, ts, username
    ))

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"status": status, "fraud_score": score, "confidence": max(0, 100-score)})

@app.route("/admin")
def admin():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get all users
    cursor.execute("SELECT * FROM users")
    users = cursor.fetchall()

    # Get history for each user
    result = {}
    for user in users:
        username = user["username"]
        cursor.execute("SELECT * FROM user_history WHERE username = %s ORDER BY ts DESC", (username,))
        history = cursor.fetchall()
        result[username] = dict(user)
        result[username]["history"] = [dict(entry) for entry in history]

    cursor.close()
    conn.close()
    return jsonify(result)

@app.route("/profiles")
def profiles():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT username,
               flight_mean, dwell_mean, mouse_mean, scroll_mean, scroll_speed, touch_mean,
               status, fraud, last_update
        FROM users
    """)
    users = cursor.fetchall()

    result = {}
    for user in users:
        username = user["username"]
        result[username] = {
            "profile": {
                "flight_mean": user["flight_mean"],
                "dwell_mean": user["dwell_mean"],
                "mouse_mean": user["mouse_mean"],
                "scroll_mean": user["scroll_mean"],
                "scroll_speed": user["scroll_speed"],
                "touch_mean": user["touch_mean"]
            },
            "status": user["status"],
            "fraud": user["fraud"],
            "last_update": user["last_update"]
        }

    cursor.close()
    conn.close()
    return jsonify(result)

if __name__ == "__main__":
    app.run(debug=True)