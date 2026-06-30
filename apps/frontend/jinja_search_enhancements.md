# Live Search Enhancements for Jinja Frontend

# Goals

Implement two UX improvements:

1. **Highlight searched keywords inside search results while the user types.**
2. **Synchronize card tag colors with the currently selected filter tag.**

---

# Feature 1: Highlight Search Terms in Results

## Desired Behaviour

User types:

```text
claude
```

Card title:

```text
Anthropic Claude Models Launch on Azure
```

Displayed result:

```html
Anthropic <mark>Claude</mark> Models Launch on Azure
```

The same highlighting should also apply to:

- Title
- Description/summary
- Optional: source name

---

## Backend Changes

No backend changes are strictly required.

The backend should continue returning normal JSON:

```json
[
  {
    "id": 1,
    "title": "Anthropic Claude Models Launch on Azure",
    "summary": "Anthropic's Claude models are now available...",
    "tags": ["llms", "research"]
  }
]
```

Highlighting should be performed entirely on the frontend.

---

# Frontend Implementation

## Step 1: Store Current Search Query

Create a variable that always contains the current query.

```javascript
let currentSearchQuery = "";
```

Update it whenever the user types:

```javascript
searchBox.addEventListener("input", () => {
    currentSearchQuery = searchBox.value.trim();
});
```

---

## Step 2: Create a Highlight Utility

Create a helper function.

```javascript
function highlightText(text, query) {

    if (!query || query.length === 0)
        return text;

    const escapedQuery =
        query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

    const regex = new RegExp(`(${escapedQuery})`, "gi");

    return text.replace(
        regex,
        '<span class="highlight">$1</span>'
    );
}
```

This:

- ignores case
- safely handles special characters
- highlights every occurrence

---

## Step 3: Render Highlighted HTML

Instead of:

```javascript
titleElement.textContent = article.title;
```

use:

```javascript
titleElement.innerHTML =
    highlightText(
        article.title,
        currentSearchQuery
    );
```

Similarly:

```javascript
summaryElement.innerHTML =
    highlightText(
        article.summary,
        currentSearchQuery
    );
```

---

## Step 4: Add Highlight Styling

Example CSS:

```css
.highlight {
    background-color: rgba(255, 0, 0, 0.25);
    color: #ff3b3b;
    font-weight: 700;
    border-radius: 4px;
    padding: 0 2px;
}
```

Alternative minimalist version:

```css
.highlight {
    color: red;
    font-weight: bold;
}
```

---

# Optional Improvement: Multi-word Search

User types:

```text
claude azure
```

Split query:

```javascript
const words = query
    .split(/\s+/)
    .filter(Boolean);
```

Loop through each word:

```javascript
function highlightText(text, query) {

    if (!query)
        return text;

    const words =
        query.split(/\s+/).filter(Boolean);

    let highlighted = text;

    words.forEach(word => {

        const escaped =
            word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

        const regex =
            new RegExp(`(${escaped})`, "gi");

        highlighted =
            highlighted.replace(
                regex,
                '<span class="highlight">$1</span>'
            );
    });

    return highlighted;
}
```

---

# Feature 2: Tag Color Synchronization

## Desired Behaviour

### State A

Current filter:

```text
All
```

All card tags:

```text
gray
```

Example:

[ llms ] [ research ] [ robotics ]

---

### State B

Current filter:

```text
llms
```

Every card tag equal to:

```text
llms
```

becomes red.

Example:

```text
[ llms ] <- red
[ research ] <- gray
[ robotics ] <- gray
```

---

# Step 1: Track Active Tag

Create a global variable.

```javascript
let activeTag = "all";
```

When user clicks a filter:

```javascript
filterButtons.forEach(button => {

    button.addEventListener("click", () => {

        activeTag =
            button.dataset.tag.toLowerCase();

        performSearch();
    });

});
```

Example HTML:

```html
<button data-tag="all">All</button>
<button data-tag="llms">LLMs</button>
<button data-tag="research">Research</button>
```

---

# Step 2: Render Card Tags Dynamically

Suppose:

```javascript
article.tags = [
    "llms",
    "research",
    "robotics"
];
```

Generate HTML:

```javascript
const tagsHTML = article.tags.map(tag => {

    const selected =
        activeTag !== "all" &&
        tag.toLowerCase() === activeTag;

    return `
        <span class="card-tag
            ${selected ? "selected-tag" : ""}">
            ${tag}
        </span>
    `;

}).join("");
```

Insert:

```javascript
tagsContainer.innerHTML = tagsHTML;
```

---

# Step 3: Add CSS

Default tag:

```css
.card-tag {
    background: #2b2b2b;
    color: #a8a8a8;
    border-radius: 8px;
    padding: 6px 12px;
}
```

Selected tag:

```css
.selected-tag {
    background: rgba(255, 0, 0, 0.15);
    color: #ff3b3b;
    border: 1px solid #ff3b3b;
}
```

---

# Example

Active filter:

```javascript
activeTag = "llms";
```

Card:

```javascript
tags: ["llms", "research"]
```

Rendered:

```html
<span class="card-tag selected-tag">
    llms
</span>

<span class="card-tag">
    research
</span>
```

Result:

- llms -> red
- research -> gray

---

# Re-render Requirement

Whenever either:

- search query changes
- filter tag changes

the card list should be re-rendered.

Typical flow:

```text
User types/clicks filter
        ↓
Fetch results
        ↓
Update currentSearchQuery
        ↓
Update activeTag
        ↓
Render cards
        ↓
Apply highlights
        ↓
Apply tag colors
```

---

# Recommended Architecture

Keep UI state centrally.

```javascript
const state = {
    query: "",
    activeTag: "all",
    results: []
};
```

Render cards only from this state.

```javascript
renderCards(state.results);
```

This approach scales well and prevents inconsistent UI behaviour.
