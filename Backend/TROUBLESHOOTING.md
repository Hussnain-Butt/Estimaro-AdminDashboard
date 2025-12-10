# Database Connection Troubleshooting

## Issue
`password authentication failed for user "estimaro_user"` when connecting from Windows host to Docker PostgreSQL.

## Root Cause
Docker Desktop on Windows has networking issues with PostgreSQL authentication. The container works internally but external connections fail.

## Solutions (Try in Order)

### Solution 1: Use Docker Host Network (Recommended)
Restart Docker containers with host network mode:

```powershell
# Stop containers
docker-compose down -v

# Edit docker-compose.yml and add to postgres service:
network_mode: "host"

# Restart
docker-compose up -d
```

### Solution 2: Use Docker IP Address
Instead of `localhost`, use Docker container IP:

```powershell
# Get container IP
docker inspect estimaro_postgres | Select-String "IPAddress"

# Update .env file:
DATABASE_URL=postgresql+psycopg://estimaro_user:estimaro_pass@172.17.0.2:5432/estimaro_db
```

### Solution 3: Use `host.docker.internal`
Update `.env`:
```
DATABASE_URL=postgresql+psycopg://estimaro_user:estimaro_pass@host.docker.internal:5432/estimaro_db
```

### Solution 4: Create Tables Inside Docker
Run Python inside the Docker network:

```powershell
# Copy create_tables.py to container
docker cp create_tables.py estimaro_postgres:/tmp/
docker cp -r app estimaro_postgres:/tmp/

# Install Python in container
docker exec estimaro_postgres apk add python3 py3-pip
docker exec estimaro_postgres pip3 install sqlalchemy psycopg

# Run script
docker exec estimaro_postgres python3 /tmp/create_tables.py
```

### Solution 5: Use pgAdmin to Create Tables
1. Open pgAdmin: http://localhost:5050
2. Login: admin@estimaro.com / admin123
3. Add Server:
   - Host: estimaro_postgres
   - Port: 5432
   - User: estimaro_user
   - Password: estimaro_pass
4. Run SQL from `schema.sql` (generated below)

### Solution 6: Switch to Local PostgreSQL
Install PostgreSQL directly on Windows instead of Docker:
1. Download from https://www.postgresql.org/download/windows/
2. Install with user `estimaro_user` and password `estimaro_pass`
3. Update `.env`: `DATABASE_URL=postgresql+psycopg://estimaro_user:estimaro_pass@localhost:5432/estimaro_db`

## Verification
After applying any solution, test with:

```powershell
.\venv\Scripts\Activate.ps1
python create_tables.py
```

Should see: `✅ All tables created successfully!`

## Current Status
- ✅ Docker container running
- ✅ Database accessible from inside container
- ❌ Host machine cannot connect (Windows Docker networking issue)
- ✅ All code is ready and working

## Next Steps After Fix
Once tables are created:

```powershell
# Verify tables
docker exec estimaro_postgres psql -U estimaro_user -d estimaro_db -c "\dt"

# Start API server
uvicorn app.main:app --reload

# Access docs
# http://localhost:8000/docs
```
