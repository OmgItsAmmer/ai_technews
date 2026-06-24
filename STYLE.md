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
