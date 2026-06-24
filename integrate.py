import os, shutil, re

def copy_file(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    print(f"Copied {src} to {dst}")

copy_file('ai-technews-admin-intake-main/static/css/style.css', 'static/admin/css/style.css')
copy_file('ai-technews-admin-intake-main/static/js/add_news.js', 'static/admin/js/add_news.js')
if os.path.exists('ai-technews-admin-intake-main/static/js/theme.js'):
    copy_file('ai-technews-admin-intake-main/static/js/theme.js', 'static/admin/js/theme.js')

copy_file('ai-technews-admin-intake-main/templates/base.html', 'templates/ainews_admin/base_intake.html')

with open('templates/ainews_admin/base_intake.html', 'r+', encoding='utf-8') as f:
    content = f.read()
    if '{% load static %}' not in content:
        content = '{% load static %}\n' + content
    
    # Replace {{ static('...') }} with {% static '...' %}
    content = re.sub(r'\{\{\s*static\([\'"]([^\'"]+)[\'"]\)\s*\}\}', r"{% static '\1' %}", content)
    
    content = content.replace("{% static 'css/style.css' %}", "{% static 'admin/css/style.css' %}")
    content = content.replace("{% static 'js/theme.js' %}", "{% static 'admin/js/theme.js' %}")
    f.seek(0)
    f.write(content)
    f.truncate()

copy_file('ai-technews-admin-intake-main/templates/admin/add_news_index.html', 'templates/ainews_admin/add_news_index.html')

with open('templates/ainews_admin/add_news_index.html', 'r+', encoding='utf-8') as f:
    content = f.read()
    
    # Check if it extends base.html and update it
    content = content.replace('{% extends "base.html" %}', '{% extends "ainews_admin/base_intake.html" %}\n{% load static %}')
    
    # Replace {{ static('...') }} with {% static '...' %}
    content = re.sub(r'\{\{\s*static\([\'"]([^\'"]+)[\'"]\)\s*\}\}', r"{% static '\1' %}", content)
    
    content = content.replace("{% static 'js/add_news.js' %}", "{% static 'admin/js/add_news.js' %}")
    f.seek(0)
    f.write(content)
    f.truncate()

if os.path.exists('ai-technews-admin-intake-main/templates/admin/base.html'):
    copy_file('ai-technews-admin-intake-main/templates/admin/base.html', 'templates/admin/base.html')
    with open('templates/admin/base.html', 'r+', encoding='utf-8') as f:
        content = f.read()
        content = content.replace("{% static 'js/theme.js' %}", "{% static 'admin/js/theme.js' %}")
        f.seek(0)
        f.write(content)
        f.truncate()

if os.path.exists('ai-technews-admin-intake-main/templates/admin/base_site.html'):
    copy_file('ai-technews-admin-intake-main/templates/admin/base_site.html', 'templates/admin/base_site.html')
    # Since we copied base_site to admin/base_site.html, it will override django admin base_site globally if not careful.
    # We should put it in ainews_admin/base_site.html
    copy_file('ai-technews-admin-intake-main/templates/admin/base_site.html', 'templates/ainews_admin/base_site.html')

print('Integration complete!')
