# Frontend App — File Reference

Django app at `apps/frontend/` that serves the public ANTIX News reader: feed browsing, saved articles, session bookmarks, infinite scroll, search/filter UX, tag conveyor animations, and the Ask AI chat panel.

Mounted at the site root via [`config/urls.py`](../config/urls.py) (`path("", include("apps.frontend.urls"))`).

---

## Directory layout

```
apps/frontend/
├── apps.py                          # Django app config
├── jinja2.py                        # Jinja2 environment globals/filters
├── urls.py                          # URL routing
├── views.py                         # Page views + JSON API handlers
├── models.py                        # SavedPost model
├── chat.py                          # Stub chat/RAG service (in-memory)
├── migrations/
│   └── 0001_initial.py              # SavedPost table
├── templatetags/
│   └── jinja_filters.py             # Duplicate join_tags filter (django-jinja)
├── templates/frontend/
│   ├── base.jinja                   # Site shell, navbar, chat panel, global JS
│   ├── feed.jinja                   # Main feed page
│   ├── saved.jinja                  # Saved articles page
│   ├── post_card.jinja              # Single article card partial
│   └── posts_fragment.jinja         # AJAX HTML partial for cards
├── static/frontend/css/
│   ├── main.css                     # Public reader styles
│   ├── admin_theme.css              # Django admin dark theme
│   └── admin_keywords.css           # Admin keyword settings page styles
└── jinja_search_enhancements.md     # Planning notes (search highlight + tag sync)
```

---

## Python modules

### `apps.py`

Registers the Django app as `apps.frontend` with label `frontend`. Standard `AppConfig`; no custom `ready()` hooks.

### `jinja2.py`

Configures the **django-jinja** environment for this app’s templates.

| Export | Purpose |
|--------|---------|
| `static` | Global — resolves `{{ static('path') }}` to versioned static URLs |
| `url` | Global — Django `reverse()` for named URL patterns |
| `join_tags` | Filter — joins a post’s tag list into a comma-separated string for `data-tags` attributes |

### `urls.py`

Maps HTTP routes to view functions.

| Path | View | Method |
|------|------|--------|
| `/` | `feed_view` | GET |
| `/saved` | `saved_view` | GET |
| `/api/save` | `api_save_post` | POST, DELETE |
| `/api/saved` | `api_get_saved` | GET |
| `/api/fetch-latest` | `api_fetch_latest` | POST |
| `/api/chat` | `api_chat` | POST |
| `/api/chat/history` | `api_chat_history` | GET |

### `views.py`

Core request handling for pages and APIs.

**Helpers**

| Function | Role |
|----------|------|
| `annotate_matched_keywords(posts)` | Sets `post.matched_keyword` when title/summary/content/tags match admin-configured keywords (featured badge) |
| `get_all_tags()` | Returns sorted unique tags from all approved posts |
| `get_tag_counts()` | Returns per-tag counts and total approved post count for the Topics dropdown |

**Page views**

| Function | Role |
|----------|------|
| `feed_view` | Main feed: filters (tag, source, dates, sort, featured, search), paginates 20 posts/page, renders `feed.jinja` or returns JSON `{ html, page, total_pages, total_count }` when `ajax=1` |
| `saved_view` | Saved articles for a `?token=` session; search via `q`; AJAX returns card HTML fragment |

**API views**

| Function | Role |
|----------|------|
| `api_save_post` | POST creates / DELETE removes a `SavedPost` for `(token, post_id)` |
| `api_get_saved` | GET returns `{ post_ids: [...] }` for bookmark hydration |
| `api_fetch_latest` | POST dispatches Celery `fetch_all_sources` task |
| `api_chat` | POST accepts `{ session_token, page_session_id, message }`; delegates to `chat.handle_chat_message` |
| `api_chat_history` | GET returns in-memory messages for the current page session |

### `models.py`

**`SavedPost`** — anonymous bookmark storage.

| Field | Purpose |
|-------|---------|
| `token` | Browser session ID (`sess_…` from `localStorage`) |
| `post_id` | ID of the saved `Post` |
| `saved_at` | Timestamp |

Unique on `(token, post_id)`. Table name: `saved_posts`.

### `chat.py`

Stub chat backend (to be replaced with real RAG/LLM later).

- Stores conversation in an **in-process dict** keyed by `(session_token, page_session_id)`.
- `page_session_id` is a UUID generated once per page load in `base.jinja` — history **resets on refresh**.
- `generate_stub_reply()` keyword-searches approved posts and returns a canned answer with `[1]`, `[2]` citation markers plus structured citation objects (`title`, `source_name`, `url`, `post_id`).

### `migrations/0001_initial.py`

Creates the `saved_posts` table for `SavedPost`.

### `templatetags/jinja_filters.py`

Registers `join_tags` via **django-jinja** `@library.filter`. Mirrors the filter in `jinja2.py` for compatibility with both registration paths.

---

## Templates (`templates/frontend/`)

### `base.jinja`

Site shell used by all public pages.

**Structure**

- Sticky floating navbar (logo, Feed/Saved links, search input, Fetch latest, Copy session, **Ask AI**)
- `{% block content %}` for page bodies
- Article detail modal (`#card-modal`)
- **AI chat panel** (`#chat-panel`) with dimmed backdrop

**Global JavaScript (inline)**

| Area | Responsibility |
|------|----------------|
| Session | `getOrCreateToken()`, `copyToken()` — `localStorage` `ainews_token` |
| Bookmarks | `hydrateSaved()`, `toggleSave()` — sync with `/api/save` and `/api/saved` |
| Modal | `openModal()`, `closeModal()` — full summary in overlay |
| Read more | `checkReadMore()` — show button when summary is clamped |
| Tag conveyor | `initTagConveyors()`, `tagsWrap()`, `buildTagConveyor()` — horizontal scroll animation for multi-line tag rows |
| Scroll | `observeCards()` — fade-in cards via `IntersectionObserver` |
| Fetch | `fetchLatestNews()` — triggers `/api/fetch-latest` |
| Chat | `openChatPanel()`, `sendChatMessage()`, citation rendering, `loadChatHistory()` |

### `feed.jinja`

Extends `base.jinja`. Main news feed UI.

- **Left sidebar**: Topics dropdown, source, date range, sort, featured checkbox, clear filters
- **Main column**: article count status bar, 3-column card grid, infinite-scroll sentinel
- **Inline `<style>`**: feed layout and filter group styles
- **Inline `<script>`**: filter state, AJAX `reloadFeed()`, `fetchNextPage()`, search debounce, `applyHighlightsAndTagColors()`

Query params: `tag`, `source`, `start_date`, `end_date`, `sort`, `featured`, `q`, `page`.

### `saved.jinja`

Extends `base.jinja`. Private saved-articles library for `?token=`.

- Grid of cards (no sidebar filters)
- Search via navbar `q` param and `reloadSavedFeed()` AJAX
- Reuses `applyHighlightsAndTagColors()` (tag highlight only when `activeTag` exists on feed)

### `post_card.jinja`

Reusable partial for one article card. Included by `feed.jinja`, `saved.jinja`, and `posts_fragment.jinja`.

| Element | Notes |
|---------|-------|
| Featured badge | Shown when `post.matched_keyword` is set |
| Title + save button | Bookmark toggle |
| Summary + Read more | Opens modal when truncated |
| Tags | `.card-tag`; active filter gets `.selected-tag` via JS |
| Footer | Source name (with verified tick if author exists), date, external Read link |

`data-id`, `data-tags`, `data-date` attributes support client-side utilities.

### `posts_fragment.jinja`

Minimal AJAX partial: loops `posts` and includes `post_card.jinja`. Returned as JSON `html` from `feed_view` and `saved_view` for infinite scroll and filter reloads.

---

## Static assets (`static/frontend/css/`)

### `main.css`

Primary stylesheet for the public reader. Linked from `base.jinja`.

| Section | Contents |
|---------|----------|
| `:root` | Design tokens (`--red`, `--surface`, fonts, etc.) |
| Navbar | `.navbar`, `.nav-links`, `.icon-btn`, `.ai-btn` |
| Grid | `.grid` — 3 columns (responsive down to 1) |
| Cards | `.card`, summary clamp, tags, footer, featured badge |
| Tag conveyor | `.card-tags--conveyor`, viewport mask, `@keyframes card-tags-conveyor` |
| Search highlight | `.highlight` |
| Active tag | `.card-tag.selected-tag` |
| Modal | `.modal-overlay`, `.modal-content` |
| Chat panel | `.chat-panel`, bubbles, citations, typing indicator, input area |

### `admin_theme.css`

Dark cinematic theme overrides for **Django admin** (global admin chrome, modules, forms, tables). Not loaded on the public feed.

### `admin_keywords.css`

Scoped styles for the admin **keyword settings** page. Matches the same dark palette as the public site.

---

## Documentation

### `jinja_search_enhancements.md`

Internal planning doc for two feed UX features (now implemented):

1. Highlight search terms in card titles/summaries while typing
2. Sync card tag colors with the active Topics filter (`.selected-tag`)

Useful as design rationale; not loaded at runtime.

---

## Request flow (summary)

```mermaid
flowchart TB
    subgraph pages [Page views]
        feed[feed.jinja]
        saved[saved.jinja]
    end

    subgraph partials [Partials]
        card[post_card.jinja]
        frag[posts_fragment.jinja]
    end

    subgraph apis [JSON APIs]
        save[/api/save]
        savedApi[/api/saved]
        fetch[/api/fetch-latest]
        chat[/api/chat]
        history[/api/chat/history]
    end

    base[base.jinja]
    views[views.py]
    chatSvc[chat.py]
    posts[(posts.Post)]
    savedDb[(SavedPost)]

    base --> feed
    base --> saved
    feed --> card
    saved --> card
    frag --> card
    views --> feed
    views --> saved
    views --> frag
    views --> save
    views --> savedApi
    views --> fetch
    views --> chat
    views --> history
    chat --> chatSvc
    views --> posts
    save --> savedDb
    savedApi --> savedDb
```

---

## External dependencies

| Dependency | Used by |
|------------|---------|
| `apps.posts.models.Post` | Feed queries, featured keywords, chat citations |
| `apps.posts.models.KeywordSetting` | Featured badge and sort |
| `apps.sources.models.Source` | Source filter dropdown |
| `apps.fetcher.tasks.fetch_all_sources` | Fetch latest button |
| django-jinja | Template engine |
| Tabler Icons (CDN) | Icons in templates |
| Google Fonts | Bebas Neue, DM Sans |

---

## Conventions

- **No separate frontend JS bundle** — behavior lives in inline `<script>` blocks in `base.jinja`, `feed.jinja`, and `saved.jinja`.
- **Session identity** — `ainews_token` in `localStorage`; saved posts and chat both reference it. Chat also uses `page_session_id` (per page load) so conversation resets on refresh.
- **Progressive enhancement** — server-rendered pagination links exist in `feed.jinja` but are hidden when JS enables infinite scroll.
- **AJAX contract** — feed/saved return `{ html }` or `{ html, page, total_pages, total_count }`; chat returns `{ answer, citations, messages }`.
