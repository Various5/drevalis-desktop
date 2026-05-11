# Billing setup — Stripe + PayPal, step by step

Everything you need to accept payments in CHF via Stripe **and** PayPal,
with feature-gated tiers (Creator / Pro / Studio). Follow top to bottom.

---

## A. Stripe — CHF + adaptive conversion

### A1. Enable the Stripe account

1. Log in at <https://dashboard.stripe.com>.
2. Top-right **Settings** → **Business settings** → **Tax and billing** →
   **Tax** → turn on **Automatic tax**. Drevalis doesn't collect VAT
   — Stripe does, based on the buyer's country.
3. Top-right **Settings** → **Product catalog** → **Currency settings**
   → set **CHF** as a supported currency (also enable EUR, USD, GBP so
   Stripe's adaptive pricing works).
4. **Settings** → **Checkout and Payment Links** → **Presentment** →
   turn on **Adaptive pricing**. This is what makes a Swiss buyer see
   CHF and a German buyer see EUR at checkout without you creating
   separate Prices.

### A2. Create three Products + six Prices (CHF)

For **each** tier, create a Product with a monthly Price and a yearly
Price:

| Product name | Monthly (CHF) | Yearly (CHF) |
|---|---:|---:|
| Drevalis Creator | 19 | 209 |
| Drevalis Pro | 49 | 539 |
| Drevalis Studio | 99 | 1089 |

Yearly = monthly × 11 (one free month on annual plans). If you change the
multiplier, update the `data-price-yearly` attrs in `marketing/public/index.html`
and `pricing.html` too.

Steps (same for each Product):

1. Dashboard → **Products** → **+ Add product**.
2. **Name:** `Drevalis Creator` (etc).
3. **Pricing model:** Recurring.
4. **Price:** 19 (for Creator monthly). **Currency:** CHF. **Billing period:**
   Monthly. Save.
5. **+ Add another price** → 209 (Creator) / 539 (Pro) / 1089 (Studio), CHF, Yearly. Save.
6. Copy the six **price IDs** (they look like `price_1P…`). You need
   them in A3.

### A3. Webhook endpoint

1. Dashboard → **Developers** → **Webhooks** → **+ Add endpoint**.
2. **Endpoint URL:** `https://license.drevalis.com/webhook/stripe`.
3. **Events to send:** select
   - `checkout.session.completed`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.payment_succeeded`
   - `invoice.payment_failed`
4. Save → copy the **Signing secret** (starts with `whsec_`).

### A4. Env vars on the VPS (license-server)

SSH to the VPS and edit `/srv/drevalis-license/.env`:

```bash
# Stripe
STRIPE_SECRET_KEY=<paste_sk_live_key_from_stripe_dashboard>
STRIPE_WEBHOOK_SECRET=<paste_whsec_from_stripe_dashboard>
STRIPE_PRICE_CREATOR_MONTHLY=price_xxx
STRIPE_PRICE_CREATOR_YEARLY=price_xxx
STRIPE_PRICE_PRO_MONTHLY=price_xxx
STRIPE_PRICE_PRO_YEARLY=price_xxx
STRIPE_PRICE_STUDIO_MONTHLY=price_xxx
STRIPE_PRICE_STUDIO_YEARLY=price_xxx
STRIPE_CURRENCY=chf
STRIPE_AUTOMATIC_TAX=true
STRIPE_ADAPTIVE_PRICING=true
```

Then:

```bash
cd /srv/drevalis-license
docker compose up -d --force-recreate
```

### A5. Test it

```bash
curl -X POST https://license.drevalis.com/checkout \
  -H 'Content-Type: application/json' \
  -d '{"tier":"creator","interval":"monthly"}'
```

Expect `{"url": "https://checkout.stripe.com/c/..."}`. Paste that URL
in a private browser window to walk through the Stripe checkout. Use
test card `4242 4242 4242 4242`, any future expiry, any CVC.

---

## B. PayPal — CHF subscriptions

> **⚠ Not yet implemented.** The license-server's `app/routes/` directory
> does not contain a `paypal.py` — there is no `/paypal/checkout` or
> `/paypal/webhook` route. The PayPal product is on the roadmap; this
> section documents what the configuration *should* look like once the
> server-side routes land. Don't follow B4–B7 verbatim until the
> server routes exist; the webhook will return 404 and the marketing
> button will silently fail.

### B1. Register a PayPal Business app

1. Log in at <https://developer.paypal.com/dashboard>.
2. **Apps & Credentials** → **Live** tab → **Create App**.
3. **App name:** `Drevalis Creator Studio`. **Type:** Merchant.
4. Save → copy **Client ID** and **Secret**.

### B2. Create three Catalog Products

1. PayPal dashboard → **Pay and Get Paid** → **Subscriptions** →
   **Products** → **+ Create product**.
2. Create three products, one per tier:
   - Name: `Drevalis Creator`. Type: SERVICE. Category: SOFTWARE.
   - Name: `Drevalis Pro`. Same settings.
   - Name: `Drevalis Studio`. Same settings.
3. Copy each product's **ID** (looks like `PROD-xxx`).

### B3. Create six Subscription Plans

For **each** of the three products create two Plans (monthly + yearly):

1. **Pricing:** Regular. **Cycle:** 1 month / 1 year. **Price:** CHF 19
   / 49 / 99 (monthly) or 209 / 539 / 1089 (yearly — monthly × 11, one month
   free). **Currency:** CHF.
2. **Setup fee:** 0. **Taxes:** inclusive. **Trial:** none.
3. Activate the plan → copy the **Plan ID** (looks like `P-xxx`).

End state: 3 Products → 6 Plans, all in CHF.

### B4. Webhook

1. Dashboard → **Webhooks** → **+ Add webhook**.
2. **Webhook URL:** `https://license.drevalis.com/paypal/webhook`.
3. **Event types:** tick:
   - `BILLING.SUBSCRIPTION.ACTIVATED`
   - `BILLING.SUBSCRIPTION.CANCELLED`
   - `BILLING.SUBSCRIPTION.SUSPENDED`
   - `BILLING.SUBSCRIPTION.PAYMENT.FAILED`
   - `PAYMENT.SALE.COMPLETED`
4. Save → copy the **Webhook ID** (`WH-xxx`).

### B5. Env vars on the VPS

Append to `/srv/drevalis-license/.env`:

```bash
# PayPal
PAYPAL_MODE=live
PAYPAL_CLIENT_ID=xxxxxxxxxxxxxxxxxxxx
PAYPAL_CLIENT_SECRET=xxxxxxxxxxxxxxxxxxxx
PAYPAL_WEBHOOK_ID=WH-xxxxxxxxxxxxxxxxxxxx
PAYPAL_PLAN_CREATOR_MONTHLY=P-xxx
PAYPAL_PLAN_CREATOR_YEARLY=P-xxx
PAYPAL_PLAN_PRO_MONTHLY=P-xxx
PAYPAL_PLAN_PRO_YEARLY=P-xxx
PAYPAL_PLAN_STUDIO_MONTHLY=P-xxx
PAYPAL_PLAN_STUDIO_YEARLY=P-xxx
```

```bash
cd /srv/drevalis-license
docker compose up -d --force-recreate
```

### B6. Enable the PayPal button on the marketing site

On the VPS, edit `/srv/drevalis-site/public/pricing.html` and add
**just before** the `<script src="/assets/site.js"></script>` tag:

```html
<script>window.PAYPAL_ENABLED = true;</script>
```

Do the same for `/srv/drevalis-site/public/index.html` if you want
PayPal buttons on the homepage tier cards too.

```bash
cd /srv/drevalis-site
docker compose up -d --build
```

Hard-reload the site — you'll see a second "Pay with PayPal" button
below each Stripe checkout button.

### B7. Test it

```bash
curl -X POST https://license.drevalis.com/paypal/checkout \
  -H 'Content-Type: application/json' \
  -d '{"tier":"creator","interval":"monthly"}'
```

Expect `{"approve_url": "https://www.paypal.com/webapps/billing/subscriptions?ba_token=…"}`.
Open it in a sandbox browser and approve with a PayPal test account.

---

## C. Tier feature locks

The license JWT carries a `features` claim. Canonical map lives in
**two places that must stay in sync**:

- Client: `src/drevalis/core/license/features.py` (`TIER_FEATURES`)
- Server: `license-server/app/crypto.py` (`TIER_FEATURES`)

Current map (canonical names — these are the literal strings the
server embeds in the JWT and the client checks against):

| Tier | Features |
|---|---|
| Creator | `basic_generation`, `scheduled_publish`, `seo_preflight` |
| Pro | Creator + `runpod`, `audiobooks`, `elevenlabs`, `character_packs`, `continuity_check`, `social_tiktok`, `multichannel`, `cross_platform_bulk` |
| Studio | Pro + `social_extended`, `social_platforms` *(legacy alias)*, `team_mode`, `api_access` |

The client `_current_feature_set()` **unions** the JWT claim with its
own per-tier defaults, so a JWT minted from a stale server map still
unlocks everything at runtime — but the JWT is supposed to be
self-describing. When you change features:

1. Update `src/drevalis/core/license/features.py` (client).
2. Update `license-server/app/crypto.py` (server) — same names, same
   per-tier composition.
3. Update the marketing pricing matrix in
   `marketing/public/pricing.html` and the shared
   `marketing/public/assets/pricing-block.html`.
4. Deploy the license-server (`cd /srv/drevalis-license && docker
   compose up -d --build`). Existing JWTs aren't re-minted — the
   client union keeps them working. New activations and heartbeats
   carry the updated claim.

---

## D. Smoke checklist before going live (Stripe-only — PayPal pending)

- [ ] `curl -X POST https://license.drevalis.com/checkout` returns a
      real Stripe URL.
- [ ] Webhook test: **Stripe dashboard → Webhooks → your endpoint →
      Send test webhook → `checkout.session.completed`** → response
      should be `200 OK`.
- [ ] Buy one Creator monthly as yourself in live mode with a real
      card. Confirm a license JWT lands in the admin dashboard with
      `tier=creator`.
- [ ] Activate that license in the desktop app on a fresh Windows VM
      → status flips to `active` and the Pro/Studio gates respect the
      JWT's `features` claim.
- [ ] Cancel it from the Stripe portal. Confirm the JWT flips to
      `state=grace` within 5 minutes (then `expired` after the 7-day
      grace window).

You're live for Stripe when all of the above pass. PayPal goes live
once the routes in section B exist on the server.
