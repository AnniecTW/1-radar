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

For My Dashboard and the event analytics page, this makes the same student the Owner of a demo club ("Illini Robotics Club") with upcoming, draft, past, paid, drop-in and cancelled events, plus 70 demo attendees with RSVPs, check-ins, views, likes and saves. Run it after `seed_profile_demo`. Re-running replaces the earlier demo host data, and `--remove` deletes all of it:

```sh
python manage.py seed_host_demo --confirm
python manage.py seed_host_demo --confirm --remove
```

## Shared image uploads (Supabase Storage)

Event covers and organization logos are stored in the team's Supabase Storage bucket, so everyone sees the same images. Add the five `SUPABASE_S3_*` values to your `.env` (ask a teammate for them privately; the names are in `.env.example`), run `pip install -r requirements.txt`, and restart the server. Without them, uploads are saved in `media/` on your computer only, and other people see a broken image.

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

## Semantic event search

Set `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` in `.env` locally or as server secrets. Optional settings are `CLOUDFLARE_EMBEDDING_MODEL` (defaults to `@cf/baai/bge-small-en-v1.5`), `CLOUDFLARE_TIMEOUT` (defaults to 5 seconds), and `CLOUDFLARE_SEMANTIC_MIN_SIMILARITY` (defaults to `0.58`; cosine similarity below this value is excluded). Tune the similarity cutoff against real searches and relevance judgments. Apply `python manage.py migrate`, then run `python manage.py rebuild_event_embeddings` to backfill published events; add `--force` to rebuild or `--all` to include drafts and ended events. Failed IDs are printed and the command is safe to rerun.

The landing page GET search uses saved 384-dimensional pgvector embeddings and falls back to the existing keyword search when Cloudflare is unavailable. Check with `python manage.py test apps.events.tests.test_semantic_search`; a configured live smoke check is `python manage.py rebuild_event_embeddings` followed by a search from the home page. On PythonAnywhere, add both secrets in the web app environment/configuration, reload the app, and confirm outbound HTTPS access to `api.cloudflare.com`. Search uses one paid/limited Cloudflare call per submitted query, while event edits only re-embed when public searchable text changes.
