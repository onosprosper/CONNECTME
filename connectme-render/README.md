# ConnectMe — Render MVP

A mobile-friendly Nigerian marketplace for local services and experience requests. This is a separate Flask implementation of the ConnectMe concept, ready for Render and PostgreSQL.

## What works
- Email/password accounts (one account can be customer and provider)
- Search providers by service, city and category
- Provider profiles and service areas
- Requests, offers, offer acceptance and booking status
- Personal activity dashboard
- Google Maps search links for provider service areas
- CSRF protection and password hashing

## Not yet implemented
Phone OTP, NIN verification, map pin validation, in-app messaging, payments, reviews, admin moderation, and email notifications. All provider profiles display as unverified. Do not request or store NIN numbers in this version.

## Run locally

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export SECRET_KEY='change-this-for-local-development'
python app.py
```

Local development uses SQLite. Production should use PostgreSQL. `db.create_all()` initializes tables on startup; introduce database migrations before making schema changes to a live service.

## Deploy to Render

1. Create a separate GitHub repository for this folder; do not put it inside the existing MYBUSINESS app.
2. Create a Render PostgreSQL database and copy its **internal database URL**.
3. In Render, create a Blueprint from the repository's `render.yaml` or create a Python web service with build command `pip install -r requirements.txt` and start command `gunicorn app:app --bind 0.0.0.0:$PORT`.
4. Set `DATABASE_URL` to the PostgreSQL URL and set a long random `SECRET_KEY` (the Blueprint generates the latter). Keep both secret. Deploy and check `/health`.
5. In Web Service Settings → Custom Domains, add `connectme.com` and optionally `www.connectme.com`. Copy the DNS values Render presents to the domain registrar. Verify the domain inside Render after DNS updates. The domain must be registered and under your control.

The `.onrender.com` address remains usable unless you disable it in Render after the custom domain works.

## Update: verification, photos and plans

- `/verification` lets signed-in users upload a public profile photo (JPEG/PNG/WebP, under 2 MB) and save a private phone number. Uploaded images are resized and re-encoded to JPEG to remove image metadata. Photos are stored in the database; no Render disk is required.
- Phone and identity/NIN status remain **unverified**. The site does not collect NIN numbers or perform identity checks. Add an approved verification provider and OTP flow before showing verified badges.
- `/subscriptions` displays proposed monthly customer and provider fees. Defaults: ₦1,000 customer and ₦3,000 provider. Set `CUSTOMER_MONTHLY_NGN` and `PROVIDER_MONTHLY_NGN` in Render to change those figures. The Register interest button records a pending choice. No payment is taken and no subscription access is granted yet.
- The visual theme now uses blue and pink.
- The new tables (`profile_photo`, `verification_record`, `subscription_interest`) are created on startup by `db.create_all()`. Existing records remain intact. Use migrations for later schema changes.

If `/request` returns HTTP 500 in Render, inspect the service logs at the time of the request and share the Python traceback with credentials redacted. The local signed-in GET and POST request flow passes; the screenshot alone does not identify the production exception.
