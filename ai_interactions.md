# AI Interactions Log

> **Stretch features only.** Only fill in the sections that apply to stretch features you attempted. If you did not attempt a stretch feature, leave its section blank or delete it. This file is not required for the core project.

---

## Agentic Workflow (SF8)

> Document your experience using an AI agent (e.g., Cursor Agent, Claude, Copilot) to make multi-step changes autonomously.

**What task did you give the agent?**

Extend the Module 3 music recommender into a first working draft of a general,
connected music-story website. The requested product separates reviewed static
stories from live concert information and treats Odd Future as an example rather
than the platform's only subject.

**Prompts used:**

- "I think we have enough for a draft, so we could start implementing."
- "We can try to use my personal Apple Music library to give me a recommendation, then the whole story thing."
- "Let's build a system that recommends a song to a playlist... go online and find out if there's a better system overall."
- "Are you able to show me a better version of this right now using your uploaded playlist?"
- Earlier design constraints included optional guided stories, free exploration,
  cross-artist universes, reviewed static chapters, source-backed questions,
  side-by-side perspectives, and artist-stated psychological context only.

**What did the agent generate or change?**

- Added a Streamlit website in `app.py`.
- Added a reviewed JSON archive, validation, transparent retrieval, grounded
  answering, and a separate Ticketmaster provider boundary.
- Added a session-only Apple Music XML importer, an inspectable personal taste
  profile, three deterministic recommendation modes, and recommendation-to-story
  navigation.
- Researched automatic playlist continuation and added playlist parsing,
  listening-based Last.fm candidates, community-tag mood/category matching,
  multi-seed evidence, and diversity-aware hybrid ranking.
- Added a one-click, explicitly synthetic live-demo playlist so a stakeholder can
  inspect the real personalization and playlist-continuation flow without asking
  a presenter to reveal personal listening history.
- Added automated tests, structured evaluation cases, an evaluation script,
  a Mermaid architecture diagram, README execution evidence, and this model card.
- Ran compilation checks, 55 automated tests, an application health check, and a
  Streamlit test harness smoke run.

**What did you verify or fix manually?**

The human corrected the AI when it prematurely turned early brainstorming into a
five-step workflow and when it treated Odd Future as the product scope. The final
draft uses a two-step implementation/check process and a general data model. Real
artist content still requires ongoing human source review before the archive can
be described as comprehensive.

The human also rejected a recommendation feature that felt detached from the
product. That feedback changed the feature into a personal-library entrance: a
real track recommendation now leads directly into the artist's story.

---

## Design Pattern (SF10)

> Document how AI helped you choose or implement a design pattern.

**Which design pattern did you use?**

Repository plus Adapter.

**How did AI help you brainstorm or implement it?**

The discussion established that reviewed history and changing concert data have
different trust requirements. AI translated that distinction into separate code
boundaries.

**How does the pattern appear in your final code?**

`ArchiveRepository` owns static validated archive access. `TicketmasterEventsClient`
adapts a changing external provider into a small normalized event result without
allowing live data to mutate the reviewed archive.
