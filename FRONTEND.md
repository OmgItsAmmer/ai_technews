# STYLE.md — AI News Platform Style Specification

> Cinematic Dark · Luxury Utilitarian · Jinja2 + FastAPI · No JS frameworks

---

## 1. Design Direction

### Aesthetic

**Cinematic Dark — Luxury Utilitarian**

Inspired by Netflix's product language crossed with a high-end editorial reader. Dense but breathable. The red accent (`#E50914`) is rationed — it appears only on the logo, active states, saved icon fills, and the copy-session button confirmation. Everything else is cold, dark, and typographically restrained.

**DFII Score: 13/15** — Execute fully.

### Differentiation Anchor

If screenshotted without the logo, the design is recognizable by: the `Bebas Neue` wordmark in Netflix red, the single-accent-on-total-black palette, and the bookmark fill animation. No other AI news reader looks like this.

**This avoids generic AI UI by using a cinematic display font and a strictly rationed accent color instead of the typical purple-gradient SaaS palette.**

---

## 2. Design System

### Fonts

| Role | Font | Rationale |
|---|---|---|
| Display / Logo | `Bebas Neue` | Cinematic weight, distinctive at small sizes, zero AI-UI associations |
| Body / UI | `DM Sans` | Restrained, legible at 11–13px, pairs with Bebas without competing |

Both loaded via Google Fonts CDN in `base.html`:
```html
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=DM+Sans:wght@400;500&display=swap" rel="stylesheet">
```

### Color Variables

```css
:root {
  --bg:           #141414;                   /* page background */
  --surface:      #1a1a1a;                   /* card background */
  --surface2:     #212121;                   /* elevated surfaces (sort menu) */
  --nav:          #0a0a0a;                   /* navbar background */
  --red:          #E50914;                   /* sole accent — logo, active, saved */
  --red-dim:      rgba(229, 9, 20, 0.14);    /* saved button background fill */
  --border:       rgba(255, 255, 255, 0.07); /* default border */
  --border-hover: rgba(255, 255, 255, 0.18); /* hover/focus border */
  --text:         #ffffff;
  --text-muted:   rgba(255, 255, 255, 0.45); /* secondary text */
  --text-dim:     rgba(255, 255, 255, 0.22); /* tertiary text, tags, dates */
  --font-display: 'Bebas Neue', sans-serif;
  --font-body:    'DM Sans', sans-serif;
}
```

### Spacing Rhythm

Base unit: `8px`. Internal card padding: `14px`. Grid gap: `10px`. Section rhythm in multiples of 8 (`8, 12, 16, 20, 24`).

### Motion Philosophy

One purposeful animation: the save bookmark icon uses a CSS `scale` keyframe on click — fast, physical, and meaningful. Nothing else moves decoratively. Card hover uses `translateY(-4px)` lift with a deep shadow. Sort menu appears instantly (no fade — snappy, utilitarian). All transitions: `0.15–0.2s ease`.

---

## 3. Template Structure

### File Tree

```
templates/
├── base.html          ← layout shell: fonts, CSS vars, navbar, static refs
├── feed.html          ← main feed page
├── saved.html         ← saved articles page
└── post_card.html     ← card partial (included in both feed and saved)

static/
└── css/
    └── main.css       ← all styles (no Bootstrap, no Tailwind)
```

---

## 4. Template Specifications

### `base.html`

The layout shell. All other templates extend this via `{% extends "base.html" %}`.

**Responsibilities:**
- Load Google Fonts CDN
- Define all CSS custom properties on `:root`
- Render the sticky navbar
- Provide `{% block content %}` for page bodies

**Navbar structure (left to right):**
1. Logo — `AI News` in `Bebas Neue`, `--red` color
2. Nav links — `Feed` (href `/`), `Sources` (href `/sources`)
3. Right cluster:
   - **Copy session button** — icon `ti-copy`, label "Copy session". On click: switches to `ti-check` + "Copied" for 2 seconds, then resets. Writes `/saved?token=<token>` to clipboard.
   - **Saved button** — icon `ti-bookmark`, label "Saved". Links to `/saved`.

**Tabler Icons** loaded via CDN (outline only):
```html
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@latest/tabler-icons.min.css">
```

**Active nav state:** Pass `active_page` from every route. Use `{% if active_page == 'feed' %}class="active"{% endif %}` on nav links.

---

### `feed.html`

Extends `base.html`. The main public-facing page served at `/`.

**Block: controls row**

Two elements, side by side:
- Search input (flex: 1, fills remaining width) — `name="q"`, `value="{{ active_q or '' }}"`, icon `ti-search` positioned inside left edge
- Sort button (36×36px icon only) — icon `ti-arrows-sort`. Clicking toggles a dropdown menu (`.sort-menu`) with two options: "Newest first" and "Oldest first". Active option highlighted in `--red`. Clicking outside closes the menu. Sort is submitted as a query param `sort=newest|oldest`.

**Block: tag filter row**

Horizontal scrollable row of pill chips. Populated dynamically:
```jinja
<span class="tag-chip {% if not active_tag %}active{% endif %}" 
      onclick="setTag(this, '')">All</span>
{% for tag in all_tags %}
  <span class="tag-chip {% if active_tag == tag %}active{% endif %}"
        onclick="setTag(this, '{{ tag }}')">{{ tag }}</span>
{% endfor %}
```
Tag filtering is client-side (JS hides/shows cards by `data-tags` attribute) for instant response. The active tag is also reflected in the URL via a hidden input so pagination preserves it.

**Block: card grid**

```jinja
<div class="grid" id="grid">
  {% for post in posts %}
    {% include 'post_card.html' %}
  {% else %}
    <p class="empty-state">No articles match your filters.</p>
  {% endfor %}
</div>
```

Grid CSS: `grid-template-columns: repeat(auto-fill, minmax(200px, 1fr))` — fills the full viewport width, adds columns as space allows (typically 4–5 on desktop).

**Block: pagination**

Simple prev/next links. Preserve all active filters in the href:
```jinja
{% if page > 1 %}
  <a href="/?page={{ page - 1 }}&q={{ active_q }}&sort={{ active_sort }}&tag={{ active_tag }}">← Previous</a>
{% endif %}
{% if page < total_pages %}
  <a href="/?page={{ page + 1 }}&q={{ active_q }}&sort={{ active_sort }}&tag={{ active_tag }}">Next →</a>
{% endif %}
```

---

### `post_card.html`

Included partial. Assumes `post` is in scope.

**Data attributes on the root `.card` element:**
```html
<div class="card"
     data-id="{{ post.id }}"
     data-tags="{{ post.tags | join(',') }}"
     data-date="{{ post.published_at.strftime('%Y-%m-%d') }}">
```

These drive client-side tag filtering and sort without page reloads.

**Card anatomy (top to bottom):**

```
┌─────────────────────────────────────┐
│ [Title text]              [■ save]  │  ← card-top
├─────────────────────────────────────┤
│ Summary text (2–3 sentences)        │  ← card-summary
├─────────────────────────────────────┤
│ [tag] [tag] [tag]                   │  ← card-tags
├─────────────────────────────────────┤
│ Author Name        Jun 18, 2026     │  ← card-footer
│ Source Name            Read →       │
└─────────────────────────────────────┘
```

**Save button state:**
- Unsaved: `ti-bookmark` outline, `--text-dim` color, ghost border
- Saved: `ti-bookmark` outline with `.saved` class → `--red` color, `--red-dim` background, `--red` border
- On toggle: `.animating` class triggers `save-pulse` keyframe (scale 1 → 1.4 → 0.88 → 1, 320ms)

```jinja
<button class="save-btn" 
        data-id="{{ post.id }}"
        onclick="toggleSave(this, '{{ post.id }}')"
        aria-label="Save article">
  <i class="ti ti-bookmark" aria-hidden="true"></i>
</button>
```

**Save button keyframe:**
```css
@keyframes save-pulse {
  0%   { transform: scale(1); }
  40%  { transform: scale(1.4); }
  70%  { transform: scale(0.88); }
  100% { transform: scale(1); }
}
.save-btn.animating i { animation: save-pulse 0.32s ease forwards; }
```

**Card hover lift:**
```css
.card {
  transition: transform 0.2s ease, border-color 0.2s, box-shadow 0.2s ease;
}
.card:hover {
  transform: translateY(-4px);
  border-color: rgba(255, 255, 255, 0.16);
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.5);
}
```

**"Read →" link:**
```jinja
<a href="{{ post.original_url }}" 
   target="_blank" 
   rel="noopener noreferrer" 
   class="read-link">Read →</a>
```

---

### `saved.html`

Extends `base.html`. Served at `/saved`.

Receives `token` from query param. Page loads all cards for saved post IDs associated with that token (fetched from the backend). Same card grid and `post_card.html` partial as the feed.

**Empty state** when no saves exist for the token:
```html
<div class="empty-state">
  <i class="ti ti-bookmark" aria-hidden="true"></i>
  <p>Nothing saved yet.</p>
  <a href="/">Back to feed</a>
</div>
```

---

## 5. Session Token System

### How it works

The session token is a portable, anonymous identifier stored in `localStorage`. It requires no login and no server-side session. Saved articles are keyed by this token in the database.

```
localStorage key: ainews_token   → e.g. "sess_abc123xyz456"
localStorage key: ainews_saved   → JSON array of post IDs e.g. ["42","7","103"]
                                   (client-side cache, source of truth is the DB)
```

### Token generation (client-side, runs once)

```javascript
function getOrCreateToken() {
  let t = localStorage.getItem('ainews_token');
  if (!t) {
    t = 'sess_' + Math.random().toString(36).slice(2, 10)
               + Math.random().toString(36).slice(2, 10);
    localStorage.setItem('ainews_token', t);
  }
  return t;
}
```

Token is generated on first visit and never regenerated unless the user clears storage.

### Cross-browser portability

The "Copy session" button writes `https://yoursite.com/saved?token=sess_xxxx` to the clipboard. When that URL is opened on another browser:

1. The `/saved` route reads `?token=sess_xxxx` from the query param
2. It passes the token to the template
3. Client-side JS stores the token into that browser's `localStorage` as `ainews_token`
4. Future saves/unsaves on that browser use the same token, syncing across browsers

### Backend table

A single lightweight table is required:

```sql
CREATE TABLE saved_posts (
  token      TEXT NOT NULL,
  post_id    INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  saved_at   TIMESTAMP DEFAULT NOW(),
  PRIMARY KEY (token, post_id)
);
```

### API endpoints (FastAPI)

```python
POST /api/save
Body: { "token": "sess_xxx", "post_id": 42 }
Response: { "saved": true }

DELETE /api/save
Body: { "token": "sess_xxx", "post_id": 42 }
Response: { "saved": false }

GET /api/saved?token=sess_xxx
Response: { "post_ids": [42, 7, 103] }
```

### Client-side save flow

```javascript
async function toggleSave(btn, postId) {
  const token = getOrCreateToken();
  const saved = btn.classList.contains('saved');
  const method = saved ? 'DELETE' : 'POST';

  await fetch('/api/save', {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token, post_id: parseInt(postId) })
  });

  btn.classList.toggle('saved');
  // trigger animation
  btn.classList.remove('animating');
  void btn.offsetWidth;
  btn.classList.add('animating');
  btn.addEventListener('animationend', () => btn.classList.remove('animating'), { once: true });
}
```

### Hydrating save state on page load

On every page load, the JS reads the token, calls `GET /api/saved?token=`, and applies `.saved` to matching card save buttons:

```javascript
async function hydrateSaved() {
  const token = getOrCreateToken();
  const res = await fetch('/api/saved?token=' + token);
  const { post_ids } = await res.json();
  document.querySelectorAll('.save-btn').forEach(btn => {
    const id = parseInt(btn.dataset.id);
    if (post_ids.includes(id)) btn.classList.add('saved');
  });
}
```

---

## 6. Client-Side Interactivity

All interactivity is vanilla JavaScript. No frameworks. No build step.

### Tag filtering

Tags filter the visible cards client-side without a page reload. Filtered cards are hidden with `display: none`. The active tag is reflected in the URL via a shallow `history.replaceState` so pagination and refreshes preserve it.

```javascript
let activeTag = '';

function setTag(el, tag) {
  activeTag = tag;
  document.querySelectorAll('.tag-chip').forEach(c => c.classList.remove('active'));
  el.classList.add('active');
  applyFilters();
  history.replaceState(null, '', updateParam('tag', tag));
}

function applyFilters() {
  const q = document.getElementById('search-in').value.toLowerCase();
  document.querySelectorAll('.card').forEach(card => {
    const tags = card.dataset.tags.toLowerCase();
    const title = card.querySelector('.card-title').textContent.toLowerCase();
    const summary = card.querySelector('.card-summary').textContent.toLowerCase();
    const tagOk = !activeTag || tags.includes(activeTag.toLowerCase());
    const searchOk = !q || title.includes(q) || summary.includes(q) || tags.includes(q);
    card.style.display = (tagOk && searchOk) ? '' : 'none';
  });
}
```

### Sort menu

The sort icon button toggles a `.sort-menu` dropdown. Clicking outside dismisses it. Selecting an option re-sorts the grid DOM in place and closes the menu.

```javascript
document.addEventListener('click', e => {
  if (!e.target.closest('.sort-wrap')) {
    document.getElementById('sort-menu').classList.remove('open');
    document.getElementById('sort-btn').classList.remove('open');
  }
});

function selectSort(order) {
  const grid = document.getElementById('grid');
  const cards = [...grid.querySelectorAll('.card')];
  cards.sort((a, b) => {
    const da = new Date(a.dataset.date), db = new Date(b.dataset.date);
    return order === 'newest' ? db - da : da - db;
  });
  cards.forEach(c => grid.appendChild(c));
}
```

### Copy session button

```javascript
function copyToken() {
  const token = getOrCreateToken();
  const url = window.location.origin + '/saved?token=' + token;
  navigator.clipboard.writeText(url);
  const btn = document.getElementById('copy-btn');
  btn.innerHTML = '<i class="ti ti-check" aria-hidden="true"></i> Copied';
  btn.classList.add('copied');
  setTimeout(() => {
    btn.innerHTML = '<i class="ti ti-copy" aria-hidden="true"></i> Copy session';
    btn.classList.remove('copied');
  }, 2000);
}
```

---

## 7. FastAPI Route Integration

### Feed route — `GET /`

```python
@router.get("/")
async def feed(
    request: Request,
    db: AsyncSession = Depends(get_db),
    q: str = Query(None),
    tag: str = Query(None),
    sort: str = Query("newest"),
    page: int = Query(1, ge=1),
):
    PAGE_SIZE = 20
    query = select(Post).where(Post.status == "approved")

    if q:
        query = query.where(
            Post.title.ilike(f"%{q}%") | Post.summary.ilike(f"%{q}%")
        )
    if tag:
        query = query.where(Post.tags.contains([tag]))

    order = Post.published_at.desc() if sort == "newest" else Post.published_at.asc()
    query = query.order_by(order)

    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    posts = (await db.execute(query.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE))).scalars().all()

    all_tags_raw = await db.execute(select(Post.tags).where(Post.status == "approved"))
    all_tags = sorted(set(t for row in all_tags_raw.scalars() for t in (row or [])))

    return templates.TemplateResponse("feed.html", {
        "request": request,
        "posts": posts,
        "page": page,
        "total_pages": math.ceil(total / PAGE_SIZE),
        "all_tags": all_tags,
        "active_q": q or "",
        "active_tag": tag or "",
        "active_sort": sort,
        "active_page": "feed",
    })
```

### Saved page route — `GET /saved`

```python
@router.get("/saved")
async def saved_page(
    request: Request,
    token: str = Query(None),
    db: AsyncSession = Depends(get_db),
):
    posts = []
    if token:
        saved_ids = (await db.execute(
            select(SavedPost.post_id).where(SavedPost.token == token)
        )).scalars().all()
        if saved_ids:
            posts = (await db.execute(
                select(Post).where(Post.id.in_(saved_ids), Post.status == "approved")
                            .order_by(Post.published_at.desc())
            )).scalars().all()

    return templates.TemplateResponse("saved.html", {
        "request": request,
        "posts": posts,
        "token": token or "",
        "active_page": "saved",
    })
```

### Save/unsave API routes

```python
@router.post("/api/save")
async def save_post(payload: SavePayload, db: AsyncSession = Depends(get_db)):
    existing = await db.get(SavedPost, (payload.token, payload.post_id))
    if not existing:
        db.add(SavedPost(token=payload.token, post_id=payload.post_id))
        await db.commit()
    return {"saved": True}

@router.delete("/api/save")
async def unsave_post(payload: SavePayload, db: AsyncSession = Depends(get_db)):
    existing = await db.get(SavedPost, (payload.token, payload.post_id))
    if existing:
        await db.delete(existing)
        await db.commit()
    return {"saved": False}

@router.get("/api/saved")
async def get_saved(token: str = Query(...), db: AsyncSession = Depends(get_db)):
    ids = (await db.execute(
        select(SavedPost.post_id).where(SavedPost.token == token)
    )).scalars().all()
    return {"post_ids": ids}
```

---

## 8. Static Files

Served via FastAPI's `StaticFiles` mount:

```python
app.mount("/static", StaticFiles(directory="static"), name="static")
```

Referenced in templates via:
```jinja
<link rel="stylesheet" href="{{ request.url_for('static', path='css/main.css') }}">
```

No `{% load static %}` tag — that is Django-only and does not exist in Jinja2.

---

## 9. Jinja2 Setup in FastAPI

```python
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")
```

Every `TemplateResponse` call must include `"request": request` in the context dict — Starlette's Jinja2 wrapper requires it.

Custom Jinja2 filter for tag lists (register once on the `templates.env`):

```python
templates.env.filters["join_tags"] = lambda tags: ", ".join(tags or [])
```

---

## 10. Operator Checklist

- [x] Clear aesthetic direction stated — Cinematic Dark / Luxury Utilitarian
- [x] DFII ≥ 8 — scored 13/15
- [x] One memorable design anchor — Bebas Neue logo in Netflix red
- [x] No generic fonts/colors/layouts — Bebas Neue + DM Sans, hardcoded dark palette
- [x] Code matches design ambition — minimal motion, rationed accent
- [x] Accessible — semantic HTML, `aria-label` on icon buttons, `aria-hidden` on decorative icons
- [x] No JS frameworks — vanilla JS only, Jinja2 templates, no React/Vue/Next
- [x] Session persistence — `localStorage` + `SavedPost` DB table, cross-browser via URL token
- [x] Full-width grid — `auto-fill` + `minmax(200px, 1fr)`, scrollable feed
