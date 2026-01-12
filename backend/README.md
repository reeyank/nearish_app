# Backend Services

This project uses a split architecture for authentication and API logic.

## 1. Auth Server (Node.js)
Handles authentication (Anonymous, Email, etc.) using `better-auth`.
- **Directory**: `auth`
- **Port**: 4000
- **Database**: `../database.sqlite` (Shared)

### Setup & Run
```bash
cd auth
npm install
npm start
```

## 2. API Server (FastAPI)
Handles application logic and verifies user sessions from the shared database.
- **Directory**: `api`
- **Port**: 8000
- **Database**: `../database.sqlite` (Shared)

### Setup & Run
```bash
cd api
pip3 install -r requirements.txt
python3 main.py
```

## 3. Expo App Integration
The Expo app is configured to talk to the Auth Server at `http://localhost:4000`.
- **Client Config**: `ios_app/lib/auth.ts`
- **Anonymous Login**: Implemented in `ios_app/app/_layout.tsx`

**Note for Android Emulators:**
If testing on Android Emulator, change `baseURL` in `ios_app/lib/auth.ts` to `http://10.0.2.2:4000`.
For physical devices, use your computer's LAN IP (e.g., `http://192.168.1.X:4000`).
