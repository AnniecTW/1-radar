# 1-radar

## Setup (macOS)

The database is a shared PostgreSQL database on Supabase (with PostGIS and pgvector), so everyone sees the same data.

1. Install GDAL, which Django's map features need, and Python 3.13:

   ```sh
   brew install gdal python@3.13
   ```

   Use the Apple Silicon Homebrew (`which brew` should print `/opt/homebrew/bin/brew`). The older Intel Homebrew in `/usr/local` builds GDAL from source, which takes hours.

2. Create a virtual environment and install the packages:

   ```sh
   /opt/homebrew/bin/python3.13 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```

3. Create `.env` (see "Updating the Django secret key" below) and add the `DATABASE_URL` line from `.env.example`. Ask a teammate for the real connection string privately; never commit it.

4. Run the server and sign in at http://127.0.0.1:8000/admin/ (add a port such as `8001` after `runserver` if 8000 is taken):

   ```sh
   .venv/bin/python manage.py runserver
   ```

   Create your own admin account with `.venv/bin/python manage.py createsuperuser`.

The tables already exist in Supabase, so you don't need to run `migrate` after cloning. When you change a model, run `makemigrations`, commit the migration file, and run `migrate` once. Pull first so two people don't create conflicting migrations.

## Demo data

To add a small, repeatable demo dataset (users, an organization, events, RSVPs, and sample activity), activate your Python environment first. Make sure `.env` points to a development database and migrations are current, then run:

```sh
python manage.py seed_mock_data --confirm
```

The command requires `--confirm` because it writes demo records to the configured development database. Without the flag, it exits with an error and writes nothing.

## Updating the Django secret key

1. Copy `.env.example` to `.env` in the project folder (the same folder as `manage.py`).
2. Generate a new key with:

   ```sh
   python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
   ```

3. Put the generated value after `DJANGO_SECRET_KEY=` in `.env`.
4. Keep `.env` private. It is ignored by Git, so don't add it to a commit.
