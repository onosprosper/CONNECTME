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

## Trust update: phone OTP and provider review

NIN/identity collection has been removed from the user flow. Phone and profile review are separate checks and neither is a safety or background-check guarantee.

- The phone form uses Termii's Send Token and Verify Token APIs. Set `TERMII_API_KEY`, your account-specific `TERMII_BASE_URL` (for example `https://v4.api.termii.com`), and an approved `TERMII_SENDER_ID` as secret Render environment variables to enable it. Without both, the send button remains disabled. Never place keys in the repository. Test with a real phone before calling this operational.
- Phone values are normalized to Nigerian `234...` mobile format. Codes expire after five minutes; Termii limits attempts to three, while the app enforces a 90-second resend delay and three local attempts. Changing a phone resets its verified status.
- Set a separate, random `ADMIN_REVIEW_KEY` of at least 32 characters in Render. Authorized staff can sign in and open `/admin/reviews/login`, then inspect and approve or reject pending provider listings. Do not share this key with providers. Existing listings have no approval record and display “Profile not reviewed” until submitted for review by editing the listing.
- Care, transport, experiences and community requests require an approved provider profile to send offers during the no-OTP testing phase. Other categories remain open during testing and display precise trust labels.
- New tables are created on startup. No columns were added to existing tables; existing users and listings remain. For future changes, introduce migrations.
- This release includes provider reports and a staff queue with suspension and restoration of listings. It does not include completed-booking reviews or background checks. Do not present ConnectMe as a safety-vetted marketplace.

## Testing mode without OTP

SMS verification is paused in the user interface. Do not configure Termii environment variables yet. Sensitive categories still require staff approval of the provider listing to send offers, but approval checks listing details only and does not establish identity or personal safety. Phone statuses remain unverified. The OTP integration code remains isolated for a future rollout.

## Safety reports

Signed-in users can report a provider from its profile. Staff open `/admin/reports` after the existing review-key login to inspect open reports, resolve or dismiss them, or suspend the listing. Suspended listings disappear from search and cannot send new offers or have pending offers accepted. Staff can restore a suspended listing in `/admin/reviews` after review. Reports are stored privately in PostgreSQL; the form explicitly says it is not monitored in real time. There is no email alert yet, so staff must check the queue regularly.

## Paystack plan payments

Set `PAYSTACK_SECRET_KEY` as a secret Render environment variable. Start with your Paystack **test** secret key (`sk_test_...`) and use a test transaction before switching to the live secret key (`sk_live_...`). Never paste the secret key into a chat, commit it, or add it to a browser script. Your Paystack business payout account is configured in your Paystack dashboard; the app does not need your bank account number.

Set `PUBLIC_BASE_URL=https://connectme-mon2.onrender.com` (or your verified custom domain). In Paystack dashboard, set the webhook URL to `https://connectme-mon2.onrender.com/payments/paystack/webhook` (use the same domain as `PUBLIC_BASE_URL`). The checkout callback is supplied by the app. Paid plans run for 30 days and require manual renewal. A webhook or callback confirms each charge by querying Paystack, checking reference, amount, NGN currency and customer email. Duplicate notifications do not extend access.

After testing both customer and provider checkout, set `REQUIRE_SUBSCRIPTION=1` on Render to require an active customer plan for posting requests and an active provider plan for sending offers. Leave this unset while testing the rest of the marketplace. Plan purchases remain available in either setting. There is no automatic recurring charge, refund workflow or in-app service-booking payment in this release. New `plan_payment` table is created by `db.create_all()`; use managed migrations before later schema edits.

## Direct bank transfers (no payment provider)

In Render, set `BANK_NAME`, `BANK_ACCOUNT_NAME`, and `BANK_ACCOUNT_NUMBER` (a 10-digit Nigerian bank account). Use an account owned by the operating business. The bank name, account name, and number are displayed to signed-in customers after they start a transfer. Leave these unset until the details have been checked. Customers receive a unique ConnectMe reference, submit their payer name and bank transaction reference, and wait for staff review. Staff sign in through `/admin/reviews/login` with `ADMIN_REVIEW_KEY` and open `/admin/payments`. A staff user cannot approve their own transfer. Staff must compare the actual bank credit, amount, date, and payer/reference against the submitted request before approval; the submitted fields alone are not payment evidence. Approval grants 30 days, and duplicate approvals are blocked. If manual transfer is the only payment option, leave `PAYSTACK_SECRET_KEY` unset. MYBUSINESS and its Paystack webhook are unaffected.

## Separate staff account

Set `ADMIN_SETUP_EMAIL` and `ADMIN_SETUP_PASSWORD` (at least 16 characters) in the **ConnectMe** Render environment and deploy once. On startup, the app creates the first staff account in the database only if no staff account exists; the password is hashed. Remove both setup variables from Render immediately after the first successful deployment. Sign in at `/admin/login`; staff reviews, safety reports, and bank payment approvals are available there. Change your password at `/admin/password`. Staff accounts do not use customer signup or the previous `ADMIN_REVIEW_KEY`; existing customer sessions and old review-key sessions cannot open staff queues. Five failed logins lock the staff account for 15 minutes. Staff decisions are recorded in `admin_audit`, while historical review data remains in place. The legacy `/admin/reviews/login` URL redirects to the new sign-in. The `admin_account` and `admin_audit` tables are created on startup. Keep `SECRET_KEY` and `DATABASE_URL` stable, and do not share passwords in chat or commit them to Git.

## Larger portraits for both sides

Provider cards now use a large photo, and public request cards give the person looking for help the same visual treatment. When posting a request, a customer can explicitly opt in to show their uploaded profile photo on that public request. Existing requests and new requests without opt-in show an initial instead. The new `request_photo_display` table is created at startup.

## Editable personal profile

Signed-in users can open `/profile` to see and edit their name, date of birth, home address, state, and city. Date of birth and home address remain on the account holder's private profile page; public provider listings and requests continue to use their existing service area and city. Profile photos can be changed through `/verification`. A separate `user_profile` table is initialized on startup, preserving existing user records.
