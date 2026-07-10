# Email Deliverability Runbook

Finguard sends transactional email through **one Gmail / Google Workspace account
per deployment** (SMTP + app password). The code does everything it can for
deliverability; the rest is DNS, which is the operator's job. This doc is the
checklist.

## What the code already does

- **Multipart** — every email ships an HTML part *and* a plain-text fallback.
- **`Reply-To`** — set to `MAIL_REPLY_TO` (defaults to `MAIL_FROM_ADDRESS`).
- **`Message-ID` + `Date`** — set explicitly on every message.
- **`List-Unsubscribe` + `List-Unsubscribe-Post`** (RFC 8058 one-click) — on every
  *suppressible* email (reminders, approval notifications), pointing at
  `/api/v1/notifications/unsubscribe`. This is the single biggest signal Gmail and
  Yahoo now weigh for bulk/transactional senders.
- **Opt-outs honoured** — suppressible mail to an opted-out recipient is never sent.

So the transport is inbox-ready. Placement now depends on domain authentication.

## What you must configure (DNS)

Sending from a plain `@gmail.com` address works but often lands in spam and looks
unprofessional. For real deliverability, send from **your own domain** and publish
these records. `MAIL_FROM_ADDRESS` is config, so switching the sender is a config
change — no code.

### 1. SPF (authorises Google to send for your domain)
```
TXT  @   v=spf1 include:_spf.google.com ~all
```

### 2. DKIM (cryptographically signs your mail)
- Google Workspace Admin → **Apps → Google Workspace → Gmail → Authenticate email**.
- Generate a key, then publish the given record:
```
TXT  google._domainkey   v=DKIM1; k=rsa; p=<public-key>
```
- Turn on signing in the admin console after the record propagates.

### 3. DMARC (policy + reporting, once SPF & DKIM align)
```
TXT  _dmarc   v=DMARC1; p=quarantine; rua=mailto:dmarc@yourdomain; fo=1
```
Start at `p=none` to observe, tighten to `p=quarantine` then `p=reject`.

### 4. Sender config
```
MAIL_FROM_ADDRESS=billing@yourdomain
MAIL_FROM_NAME=Your Business
MAIL_REPLY_TO=support@yourdomain      # optional
```

## Volume & scaling

- Per-account send caps: **~500/day** (free Gmail), **~2,000/day** (Workspace).
- Higher volume → **Workspace SMTP relay** (`smtp-relay.google.com`, ~10,000/day),
  or graduate to a dedicated ESP (SendGrid / SES). That migration also unlocks
  **programmatic bounce & complaint handling**, which Gmail SMTP does not expose —
  the one deliverability capability out of reach on the current setup.

## Verifying it works

- Send a test to a `mail-tester.com` address; aim for 9–10/10.
- Check headers in Gmail (**Show original**): `SPF: PASS`, `DKIM: PASS`,
  `DMARC: PASS`.
- Confirm the one-click unsubscribe renders in Gmail's header (it appears next to
  the sender name for `List-Unsubscribe`-enabled mail).
