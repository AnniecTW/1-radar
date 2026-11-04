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

The shared development Supabase database already contains the demo dataset. If your `.env` points to that same database, the demo records are shared and you do not need to seed them again.

To add the demo dataset to a different or empty development database, activate your Python environment, make sure migrations are current, then run:

```sh
python manage.py seed_mock_data --confirm
```

The command requires `--confirm` because it writes demo users, an organization, events, RSVPs, and sample activity to the configured database. Without the flag, it exits with an error and writes nothing. Do not run it against a production database.

For the Profile and Preferences pages, this adds a filled-in student (`alex.chen@demo.example.edu`, same demo password as `seed_mock_data`) with four followed organizations and ten events to fill the dashboard. Those events also appear on the landing page. It needs the dataset above and is safe to re-run:

```sh
python manage.py seed_profile_demo --confirm
```

## Sending real emails (verification links)

Without email settings, Radar prints emails in the terminal running `runserver` and sends nothing. To deliver real email, add these to `.env` and restart the server:

```
EMAIL_HOST_USER=your.address@gmail.com
EMAIL_HOST_PASSWORD=your-16-character-app-password
```

For Gmail, turn on 2-Step Verification and create an App Password (Google Account → Security → App passwords); your normal password will not work. For another provider also set `EMAIL_HOST` and `EMAIL_PORT` (defaults: `smtp.gmail.com`, `587`). Optionally set `DEFAULT_FROM_EMAIL`; it defaults to `EMAIL_HOST_USER`.

## Updating the Django secret key

1. Copy `.env.example` to `.env` in the project folder (the same folder as `manage.py`).
2. Generate a new key with:

   ```sh
   python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
   ```

3. Put the generated value after `DJANGO_SECRET_KEY=` in `.env`.
4. Keep `.env` private. It is ignored by Git, so don't add it to a commit.
