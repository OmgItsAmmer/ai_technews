import os

files_to_fix = [
    'templates/admin/base.html',
    'templates/admin/base_site.html',
    'templates/ainews_admin/base_site.html'
]

for filepath in files_to_fix:
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        content = content.replace("{% static 'css/style.css' %}", "{% static 'admin/css/style.css' %}")
        content = content.replace("{% static 'js/theme.js' %}", "{% static 'admin/js/theme.js' %}")
        content = content.replace("{% static 'js/add_news.js' %}", "{% static 'admin/js/add_news.js' %}")
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f'Fixed {filepath}')
