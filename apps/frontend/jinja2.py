from django.templatetags.static import static
from django.urls import reverse
from jinja2 import Environment

def environment(**options):
    env = Environment(**options)
    env.globals.update({
        'static': static,
        'url': reverse,
    })
    
    # Custom filter for joining tags as requested in FRONTEND.md
    env.filters["join_tags"] = lambda tags: ", ".join(tags or [])
    
    return env
