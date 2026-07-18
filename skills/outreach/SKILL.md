---
name: outreach
description: Draft personalized cold-email pitches for local business leads (jewellers, cafes, dental clinics) stored in ~/second-brain/leads/inbox/. Use when asked to "draft pitches", "process leads", or during the morning run.
---

# Outreach Skill — Neuron

## What to do
1. Read every `.md` lead file in `~/second-brain/leads/inbox/` with `status: new`.
2. For each lead, fetch/read its website homepage (if it has one) and pull out
   2-3 specific observations (design outdated? no online menu? no booking?
   good Google rating but no website?).
3. Write a personalized email draft and save it:
   `~/second-brain/drafts/YYYY-MM-DD/<lead-slug>.md`
4. Fill in the lead file's "Pitch angle" section and move `status: new` →
   `status: drafted`.

## Email rules (STRICT)
- **Language:** simple, plain English. 120 words MAX. Owner is busy.
- **Structure:** 1 line specific observation → 1 line what you offer → 1 line
  proof (portfolio link) → 1 soft CTA.
- **Portfolio link:** <your portfolio URL>
- **Sender:** <your name>, web developer, <your city>.
- **NEVER:** fake claims ("I noticed 50% of your customers..."), pushy sales
  tone, "limited time offer", or a generic template feel. Every email must
  name the business and include one REAL observation.
- **Niche angles:**
  - Jewellery: catalog/gallery website, WhatsApp inquiry button, trust
    (reviews) showcase
  - Cafe: online menu + QR ordering page, Google Business optimization,
    Instagram-worthy site
  - Dental: appointment booking page, patient reviews, "near me" search
    visibility
- If the lead has no website at all → that's the strongest angle, base the
  email on it.
- If no email address was found → still draft it, but flag at the top:
  `⚠️ No email — send via Instagram DM or WhatsApp`.

## Draft file format
```markdown
---
to: <email or "DM">
business: <name>
niche: <niche>
status: ready_for_review
---
Subject: <short, specific — business name included>

<email body>
```

## Safety
- NEVER send emails yourself. Drafts only. The human reviews and sends.
- Max 15 drafts per run.

## Related
- [[🧠 NEURON HUB|NEURON HUB]]
- [[CLAUDE]]
