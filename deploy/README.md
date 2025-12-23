# Estimaro Production Deployment - Quick Reference

## Step-by-Step Deployment

### Step 1: Copy Files to Server

Via RDP, copy these folders to `C:\Estimaro\`:
- `Backend` folder
- `Frontend` folder  
- `deploy` folder

### Step 2: Install Dependencies on Server

```powershell
# Python dependencies
cd C:\Estimaro\Backend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium

# Node dependencies
cd C:\Estimaro\Frontend
npm install
npm run build
```

### Step 3: Configure Environment

```powershell
# Copy and edit the template
copy C:\Estimaro\deploy\.env.production.template C:\Estimaro\Backend\.env

# Edit the .env file with your actual credentials
notepad C:\Estimaro\Backend\.env
```

### Step 4: Start Everything

```powershell
# Run the master startup script
C:\Estimaro\deploy\start_all.bat
```

### Step 5: Login to Vendor Sites

In the Chrome window that opened:
1. Navigate to https://my.alldata.com → Login
2. Navigate to https://www.partslink24.com → Login
3. Navigate to https://speeddial.worldpac.com → Login
4. Navigate to https://shop.ssfautoparts.com → Login

### Step 6: Test

- Frontend: http://your-server-ip/
- API Docs: http://your-server-ip:8000/docs

---

## Files in deploy folder:

| File | Purpose |
|------|---------|
| `start_chrome_debug.bat` | Start Chrome with CDP debugging |
| `start_backend.bat` | Start Python backend |
| `start_frontend.bat` | Start frontend server |
| `start_all.bat` | Master script - starts everything |
| `.env.production.template` | Environment variables template |
| `README.md` | This file |
