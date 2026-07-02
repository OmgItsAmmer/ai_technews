from django_jinja import library

from apps.frontend import source_colors

@library.filter
def join_tags(tags):
    return ", ".join(tags or [])

@library.filter(name="source_color")
def source_color_filter(source):
    return source_colors.source_color(source)
