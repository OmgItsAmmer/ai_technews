# Jinja2 Integration Reference

Yes, **this project is already fully compatible with Jinja2 templates**. It has been pre-configured using `django-jinja`, which integrates Jinja2 directly into Django's template engine list.

---

## Current Configuration

### 1. Requirements
The dependencies in `requirements.txt` include:
```text
django-jinja>=2.11
```

### 2. Template Engines Settings
In `config/settings/base.py`, the `TEMPLATES` settings array defines two backend engines. The Jinja2 engine is registered first:

```python
TEMPLATES = [
    {
        "BACKEND": "django_jinja.backend.Jinja2",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "match_extension": ".jinja",
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            # ...
        },
    },
]
```

---

## How to Use Jinja2 in the Project

### 1. Template Naming Convention
Because `"match_extension": ".jinja"` is specified, the template engine determines which engine to use based on the file extension:
* **Jinja2:** Name your template files with a `.jinja` extension (e.g., `index.jinja`).
* **Django Templates:** Name your template files with a `.html` extension (e.g., `index.html`) to fall back to the standard Django engine (useful for third-party apps like the Django Admin panel).

### 2. Rendering a Jinja Template in a View
You can render Jinja templates using standard Django shortcuts like `render` without any extra setup:

```python
from django.shortcuts import render

def home_view(request):
    context = {"news_items": ["item1", "item2"]}
    # Django resolves this using django_jinja because of the .jinja extension
    return render(request, "frontend/home.jinja", context)
```

### 3. Key Differences in Syntax
When writing `.jinja` templates, you can use Jinja2 syntax instead of Django template syntax:
* **Function Calls:** You can call python methods/functions with arguments directly in your templates:
  ```jinja
  {{ my_string.upper() }}
  {{ request.user.has_perm('can_edit') }}
  ```
* **Comments:** Uses `{# comment #}`.
* **Imports:** You can import macros from other templates:
  ```jinja
  {% import "macros.jinja" as macros %}
  ```
