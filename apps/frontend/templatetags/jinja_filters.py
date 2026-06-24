from django_jinja import library

@library.filter
def join_tags(tags):
    return ", ".join(tags or [])
