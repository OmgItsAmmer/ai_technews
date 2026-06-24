import json
import math
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator
from django.db.models import Q
from .models import SavedPost
from apps.posts.models import Post

def get_all_tags():
    # Retrieve all unique tags from approved posts
    all_tags_lists = Post.objects.filter(status='approved').exclude(tags__isnull=True).values_list('tags', flat=True)
    tags = set()
    for tag_list in all_tags_lists:
        if isinstance(tag_list, list):
            tags.update(tag_list)
    return sorted(list(tags))

from django.db.models.functions import Coalesce

def feed_view(request):
    q = request.GET.get('q', '')
    tag = request.GET.get('tag', '')
    sort = request.GET.get('sort', 'newest')
    source_id = request.GET.get('source', '')
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')
    page_num = int(request.GET.get('page', 1))

    queryset = Post.objects.filter(status='approved')
    
    if q:
        queryset = queryset.filter(Q(title__icontains=q) | Q(summary__icontains=q))
    
    if tag:
        queryset = queryset.filter(tags__contains=[tag])
        
    queryset = queryset.annotate(sort_date=Coalesce('published_at', 'fetched_at'))

    if source_id:
        queryset = queryset.filter(source_id=source_id)
        
    if start_date:
        queryset = queryset.filter(sort_date__date__gte=start_date)
        
    if end_date:
        queryset = queryset.filter(sort_date__date__lte=end_date)

    if sort == 'newest':
        queryset = queryset.order_by('-sort_date')
    else:
        queryset = queryset.order_by('sort_date')

    paginator = Paginator(queryset, 20)
    page_obj = paginator.get_page(page_num)
    
    all_tags = get_all_tags()
    
    from apps.sources.models import Source
    from apps.sources.management.commands.seed_sources import SEED_SOURCES
    seeded_names = [s['name'] for s in SEED_SOURCES]
    all_sources = Source.objects.filter(name__in=seeded_names).order_by('name')

    context = {
        'posts': page_obj.object_list,
        'page': page_num,
        'total_pages': paginator.num_pages,
        'all_tags': all_tags,
        'all_sources': all_sources,
        'active_q': q,
        'active_tag': tag,
        'active_sort': sort,
        'active_source': source_id,
        'active_start_date': start_date,
        'active_end_date': end_date,
        'active_page': 'feed'
    }
    
    if request.GET.get('ajax') == '1' or request.headers.get('x-requested-with') == 'XMLHttpRequest':
        from django.template.loader import render_to_string
        html = render_to_string('frontend/posts_fragment.jinja', context, request=request)
        return JsonResponse({
            'html': html,
            'page': page_num,
            'total_pages': paginator.num_pages,
        })

    return render(request, 'frontend/feed.jinja', context)

def saved_view(request):
    token = request.GET.get('token', '')
    q = request.GET.get('q', '')
    posts = []
    
    if token:
        saved_ids = SavedPost.objects.filter(token=token).values_list('post_id', flat=True)
        if saved_ids:
            queryset = Post.objects.filter(id__in=saved_ids, status='approved')
            if q:
                queryset = queryset.filter(Q(title__icontains=q) | Q(summary__icontains=q))
            posts = queryset.order_by('-published_at', '-fetched_at')

    context = {
        'posts': posts,
        'token': token,
        'active_q': q,
        'active_page': 'saved'
    }

    if request.GET.get('ajax') == '1' or request.headers.get('x-requested-with') == 'XMLHttpRequest':
        from django.template.loader import render_to_string
        html = render_to_string('frontend/posts_fragment.jinja', context, request=request)
        if not posts:
            html = '<div class="empty-state" style="grid-column: 1 / -1;"><i class="ti ti-bookmark" aria-hidden="true"></i><p>No matching saved articles found.</p></div>'
        return JsonResponse({
            'html': html,
        })

    return render(request, 'frontend/saved.jinja', context)

@csrf_exempt
@require_http_methods(["POST", "DELETE"])
def api_save_post(request):
    try:
        data = json.loads(request.body)
        token = data.get('token')
        post_id = data.get('post_id')
        
        if not token or not post_id:
            return JsonResponse({'error': 'Missing token or post_id'}, status=400)
            
        if request.method == "POST":
            SavedPost.objects.get_or_create(token=token, post_id=post_id)
            return JsonResponse({'saved': True})
            
        elif request.method == "DELETE":
            SavedPost.objects.filter(token=token, post_id=post_id).delete()
            return JsonResponse({'saved': False})
            
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@require_http_methods(["GET"])
def api_get_saved(request):
    token = request.GET.get('token')
    if not token:
        return JsonResponse({'error': 'Missing token'}, status=400)
        
    ids = list(SavedPost.objects.filter(token=token).values_list('post_id', flat=True))
    return JsonResponse({'post_ids': ids})


@csrf_exempt
@require_http_methods(["POST"])
def api_fetch_latest(request):
    try:
        from apps.fetcher.tasks import fetch_all_sources
        fetch_all_sources.delay()
        return JsonResponse({'status': 'dispatched'})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

