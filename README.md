<div align="center">

<img src="doc/banner.svg" alt="Radar: find and host campus events in one place" width="100%">

# Radar

### Find and host campus events in one place

![Python](https://img.shields.io/badge/Python-3.13-102A4C?logo=python&logoColor=white)
![Django](https://img.shields.io/badge/Django-6.1-102A4C?logo=django&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-PostGIS%20%2B%20pgvector-102A4C?logo=postgresql&logoColor=white)
![AI](https://img.shields.io/badge/AI%20search-Cloudflare%20Workers%20AI-C65024?logo=cloudflare&logoColor=white)

[About](#about-radar) | [Features](#main-features) | [Why Radar](#why-radar) | [Install](#installation) | [Environment](#configure-environment-variables) | [Database](#set-up-the-database) | [Run](#run-the-application) | [AI Search](#use-the-ai-functionality)

</div>

## About Radar

**Startup name:** Radar

**Problem being solved:** Campus events are scattered across flyers, Instagram, group chats, email lists and department sites, so students miss events they would enjoy. Hosts have to post the same event in many places, and they can't easily tell whether it worked, because attendance is tracked on paper or not at all.

**Target users:**

- **Students** who want to find events, meet people or keep up with clubs they like
- **Student organizations (RSOs)** that promote events and need to report turnout
- **Campus staff and departments** that run events and need capacity limits and attendance records

**Core value proposition:** One place to find and host campus events. Students search in plain language and see what's happening nearby, without checking a dozen channels. Hosts publish once, then see who's coming and how the event performed.

## Main features

**For students**

- Browse upcoming events on the home page, with keyword search and category filters
- **AI search:** describe what you want in plain language, such as "a relaxed event this weekend"
- Explore Map: find events by location, with date, category and price filters
- Event pages with RSVP, waitlist and cancel; drop-in events use "Interested", and paid events link to the host's ticket page
- Save and like events, and follow organizations
- A Profile page with upcoming RSVPs, saved events, followed organizations, past events and attendance
- Preferences for interests, notifications and account settings
- A notification center for RSVP, waitlist and event updates
- Sign up, email verification, interest onboarding and password reset

**For hosts**

- Create Event: a manual form with draft and publish, map pin, cover image, and RSVP, drop-in or paid options
- My Dashboard: upcoming events, drafts, past events and check-in assignments, plus edit, publish and cancel
- Event analytics: views, likes, saves, RSVPs, attendance rate, a funnel, charts, traffic sources and audience breakdown, plus attendee CSV export
- Organization profiles with Owner, Admin and Check-in Staff roles, and a verified badge that Radar admins approve

## Why Radar

Students can already find events on Instagram, in group chats, on campus calendars and on ticketing sites. Radar doesn't replace all of them. It's for people who want campus events in one place, from finding one to showing up.

| Alternative | Where it falls short | Why someone might prefer Radar |
|---|---|---|
| Instagram and group chats | You mostly see accounts and chats you already follow, and posts get buried | Browse all campus events by date, category and location |
| Campus and department calendars | Good for listings, but spread across sites and usually not built around your interests | One searchable place, with plain-language AI search |
| Eventbrite and general ticketing sites | Built for selling tickets to any event, not for campus life | Free RSVPs and waitlists, campus-only events, verified student organizations |
| Google Forms and spreadsheets | Hosts build sign-ups by hand and track results themselves | Capacity, waitlists and analytics are built in, with attendee export |

**What sets Radar apart:**

- **Find events by meaning:** search for "a relaxed event this weekend" instead of guessing keywords.
- **See what's nearby:** a campus map with date, category and price filters.
- **One flow for students and hosts:** the event a host publishes is the one students find, RSVP to and save, and the host sees the results.
- **Campus trust:** verified organizations and campus-only events.

## Built with

Django 6.1 and Python 3.13 · PostgreSQL with PostGIS and pgvector (hosted on Supabase) · Supabase Storage for images · Cloudflare Workers AI for search embeddings · MapTiler and Leaflet for maps

## Installation

These steps are written for and tested on macOS with Apple Silicon. On other systems, install GDAL and GEOS with your package manager, then set `GDAL_LIBRARY_PATH` and `GEOS_LIBRARY_PATH` in `.env` to the location of those libraries.

1. Install Python 3.13 and GDAL, which Django's map features need:

   ```sh
   brew install gdal python@3.13
   ```

   Use the Apple Silicon Homebrew (`which brew` should print `/opt/homebrew/bin/brew`). The older Intel Homebrew in `/usr/local` builds GDAL from source, which takes hours.

2. Get the code:

   ```sh
   git clone -b first-draft https://github.com/AnniecTW/1-radar.git
   cd 1-radar
   ```

## Install dependencies

Create a virtual environment, then install the packages listed in `requirements.txt`:

```sh
/opt/homebrew/bin/python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The remaining commands assume the virtual environment is active. Run `pip install -r requirements.txt` again whenever you pull changes to that file.

## Configure environment variables

Settings and secrets live in a `.env` file in the same folder as `manage.py`. Git ignores this file, so never commit it, and share real values privately rather than in a group chat.

```sh
cp .env.example .env
```

Generate a Django secret key and paste it after `DJANGO_SECRET_KEY=`:

```sh
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

| Variable | Needed for | Required? |
|---|---|---|
| `DJANGO_SECRET_KEY` | Django security | Yes |
| `DATABASE_URL` | PostgreSQL connection string | Yes |
| `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` | AI search | For AI search; otherwise search falls back to keywords |
| `MAPTILER_API_KEY` | Explore Map tiles ([free key](https://www.maptiler.com/)) | For the map; otherwise it shows "Map unavailable" |
| `SUPABASE_S3_ENDPOINT`, `SUPABASE_S3_REGION`, `SUPABASE_S3_ACCESS_KEY_ID`, `SUPABASE_S3_SECRET_ACCESS_KEY`, `SUPABASE_S3_BUCKET` | Shared image uploads | Optional; without all five, uploads stay in `media/` on your computer and other people can't see them |
| `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | Sending real emails | Optional; otherwise emails print in the terminal running the server |
| `EMAIL_HOST`, `EMAIL_PORT`, `DEFAULT_FROM_EMAIL` | Other email providers | Optional; default to Gmail's server and `EMAIL_HOST_USER` |
| `GDAL_LIBRARY_PATH`, `GEOS_LIBRARY_PATH` | Map libraries in a non-Homebrew location | Optional |
| `CLOUDFLARE_EMBEDDING_MODEL`, `CLOUDFLARE_TIMEOUT`, `CLOUDFLARE_SEMANTIC_MIN_SIMILARITY` | Tuning AI search | Optional |

The server reads `.env` only when it starts, so restart it after any change.

**Image uploads:** in Supabase, create a public Storage bucket, then copy the endpoint and region and create an access key under Project Settings → Storage → S3 Connection. Bucket names are case-sensitive.

**Real emails with Gmail:** turn on 2-Step Verification and create an App Password (Google Account → Security → App passwords). Your normal password will not work.

## Set up the database

Radar needs PostgreSQL with the PostGIS and pgvector extensions, and a connection that supports SSL. Choose one option.

**Option A: use the team's shared database.** Ask a teammate for the `DATABASE_URL` and add it to `.env`. Its tables and demo data already exist, and everyone sees the same data. After pulling new code, run `python manage.py migrate` to apply any new migrations.

**Option B: use your own database**, such as a free Supabase project. Add its connection string to `.env` as `DATABASE_URL`, then create the tables and, optionally, the demo data, in this order:

```sh
python manage.py migrate
python manage.py seed_mock_data --confirm
python manage.py seed_profile_demo --confirm
python manage.py seed_host_demo --confirm
python manage.py seed_map_demo --confirm
```

The seed commands write demo users, organizations, events and activity, so they need `--confirm`. Don't run them against a production database. Each one is safe to re-run, but `seed_host_demo` replaces its earlier data, including any changes you made to its events. To delete that data, run `python manage.py seed_host_demo --confirm --remove`.

`seed_map_demo` dates its events from the day you run it, so after about a week they are in the past and Explore Map looks nearly empty. Re-run it to refresh them.

When you change a model, pull first so two people don't create conflicting migrations, then run `makemigrations`, commit the migration file, and run `migrate`.

## Run the application

```sh
python manage.py runserver
```

Open http://127.0.0.1:8000/. If port 8000 is taken, run `python manage.py runserver 8001` and use that port instead.

**Demo accounts** (development only; password `RadarDemo-Only-2026!`). The shared database already has them. On your own database, run the seed commands above first.

| Email | Use it to see |
|---|---|
| `alex.chen@demo.example.edu` | A filled-in Profile, plus My Dashboard and analytics as the owner of a demo club |
| `profile-demo-host@demo.example.edu` | Another host, useful for testing as a visitor to Alex's events |
| `owner@`, `admin@`, `checkin@`, `attendee1@`, `attendee2@demo.example.edu` | Club roles: owner, admin, check-in staff and attendees. They start at interest onboarding |

Open **My Dashboard → Analytics** on *Halloween Hack Night* to see an event with full data.

To open the admin site at `/admin/`, create an account with `python manage.py createsuperuser`.

## Use the AI functionality

Radar's AI feature is **AI search**, which finds events by meaning instead of exact words. For example, "somewhere to meet people and unwind" can find a social event even if those words aren't in its description.

**How it works:** Radar turns each event's title, description, categories, location and price into a 384-dimension embedding with Cloudflare Workers AI (`@cf/baai/bge-small-en-v1.5`), and stores it in PostgreSQL with pgvector. A search embeds your query the same way, then ranks events by cosine similarity and leaves out weak matches (below `0.58` by default).

**To set it up:**

1. Add `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` to `.env` and restart the server. The token needs permission to use Workers AI.
2. Check the connection. This makes one Cloudflare call:

   ```sh
   python manage.py smoke_check_embeddings
   ```

3. Create embeddings for existing events. The shared database already has them, so this is only needed for a new database. It prints any failed events and is safe to re-run. Add `--force` to rebuild all, or `--all` to include drafts and ended events.

   ```sh
   python manage.py rebuild_event_embeddings
   ```

**To use it:**

1. Use the search box in the top bar, signed in or signed out. It appears on every page except Explore Map, whose top bar searches the map by keyword only.
2. Turn on the **AI** switch next to the search box. Hover over it for a tip.
3. Type a phrase such as `a relaxed event this weekend` and search. You land on the home page, and the results appear in its browse section.

New and edited events get embeddings automatically when their searchable text changes. If Cloudflare is unavailable or the keys are missing, the page says "AI search is temporarily unavailable" and shows keyword matches instead, and saving events still works. Each AI search makes one call to Cloudflare, which has usage limits.

**On a deployed server:** add both Cloudflare values as server secrets, reload the app, and make sure the server can reach `api.cloudflare.com` over HTTPS.

## Run the tests

```sh
python manage.py test
```

Tests create a temporary database, so your `DATABASE_URL` user needs permission to create databases. To run only the AI search tests:

```sh
python manage.py test apps.events.tests.test_semantic_search
```
