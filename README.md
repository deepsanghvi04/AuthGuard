# AuthGuard with NeonDB

Lightweight demo of continuous behavioral authentication using a Flask backend with NeonDB PostgreSQL database and static frontend files.

## Setup

### 1. NeonDB Database Setup

1. Go to [Neon Console](https://console.neon.tech/) and create a new project
2. Copy your connection string from the dashboard (it looks like: `postgresql://username:password@hostname/database?sslmode=require`)
3. Update the `.env` file in your project root with your connection string:

```
DATABASE_URL=postgresql://username:password@hostname/database?sslmode=require
```

### 2. Install Dependencies

Create a virtual environment and install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 4. Test Database Connection

Before running the app, test your database connection:

```powershell
python test_db.py
```

This will verify your NeonDB connection and create the necessary tables.

### 5. Run the Application

```powershell
python app.py
```

### 4. Access the Application

Open `index.html` in a browser (or serve the folder with a simple static server).

## Database Schema

The application creates two tables automatically:

- `users`: Stores user profiles and authentication data
- `user_history`: Stores behavioral verification history

## API Endpoints

- `POST /register`: Register a new user
- `POST /login`: Authenticate user login
- `POST /verify`: Continuous behavioral verification
- `GET /admin`: Admin view of all users (requires admin secret)
- `GET /profiles`: User profiles overview

## Notes

- The backend now uses NeonDB PostgreSQL instead of local JSON files
- All behavioral data is stored securely in the database
- The demo uses `http://127.0.0.1:5000` endpoints from the frontend