# Radar: Updated Product Scope (P2-A3)

**Startup:** Radar is a campus event discovery and hosting platform. The first version is for UIUC and Champaign-Urbana.

**Problem:** Campus events are scattered across flyers, Instagram, group chats, email lists and department sites, so students miss events they would enjoy. Hosts post the same event in many places and can't tell whether it worked, because attendance is tracked on paper or not at all.

**Target users:**

- **Students** who want to find events, meet people and keep up with clubs they like
- **Registered Student Organizations (RSOs)** that promote events and report turnout
- **Campus staff and departments** that need capacity limits and attendance records

## Three core features

1. **AI-powered discovery.** Students describe what they want in plain language ("a relaxed event this weekend") and get events ranked by meaning. Search is backed by an Explore Map with date, category, price and walking-distance filters, a popularity heat map, and "Recommended for you" events based on chosen interests.
2. **Event hosting with RSVP.** Verified campus members create events with drafts, a map pin and a cover image, under an organization with Owner, Admin and Check-in Staff roles. Attendees RSVP with capacity limits and an automatic waitlist. Drop-in events use "Interested", and paid events link to the host's own ticket page. With Snap-a-Flyer, a host uploads a photo of an existing flyer and AI fills in the event form for them to review.
3. **Host analytics.** Each event has a dashboard with views, likes, saves, RSVPs, attendance rate, a funnel, traffic sources and audience breakdown, plus an attendee CSV export.

## Changes since P2-A2

Compared with the P2-A2 product requirements document (PRD v1.1, October 17, 2026):

- **Ticketing:** Radar no longer issues its own QR tickets. Paid events link to the host's ticket page; free events keep RSVP, capacity and the waitlist inside Radar.
- **Snap-a-Flyer:** a first version is built (Moondream 3.1 on Cloudflare Workers AI). It runs during the upload instead of in a Celery task queue, and opens the normal Create Event form pre-filled for review instead of a separate review screen.
- **AI search:** built as embedding search (BGE-small through Cloudflare Workers AI, ranked in PostgreSQL with pgvector) with an AI toggle and keyword fallback, instead of LLM query parsing.
- **Recommendations:** rule-based interest matching for now; ranking with event embeddings is planned.
- **Organizations:** the Editor role was dropped. Radar admins now approve a verified badge for organizations.
- **Analytics:** traffic sources and audience breakdown, listed as stretch goals in the PRD, are built.
- **Tech stack:** Django 6.1 and Python 3.13 instead of Django 5.2 and Python 3.12; plain Django JSON views instead of Django REST Framework; PostgreSQL with PostGIS and pgvector hosted on Supabase; MapTiler maps.
