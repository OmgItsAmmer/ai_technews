import json
import math
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator
from django.db.models import Q
from .models import SavedPost
from apps.posts.models import Post, KeywordSetting


def annotate_matched_keywords(posts):
    setting = KeywordSetting.objects.first()
    keywords = [k.strip() for k in setting.keywords.split(",") if k.strip()] if setting else []
    
    if not keywords:
        for post in posts:
            post.matched_keyword = None
        return
        
    for post in posts:
        post.matched_keyword = None
        title = (post.title or "").lower()
        summary = (post.summary or "").lower()
        raw = (post.raw_content or "").lower()
        tags_str = " ".join(post.tags or []).lower()
        for kw in keywords:
            kw_lower = kw.lower()
            if kw_lower in title or kw_lower in summary or kw_lower in raw or kw_lower in tags_str:
                post.matched_keyword = kw
                break


def get_all_tags():
    # Retrieve all unique tags from approved posts
    all_tags_lists = Post.objects.filter(status='approved').exclude(tags__isnull=True).values_list('tags', flat=True)
    tags = set()
    for tag_list in all_tags_lists:
        if isinstance(tag_list, list):
            tags.update(tag_list)
    return sorted(list(tags))


def get_tag_counts():
    counts = {}
    for tag_list in Post.objects.filter(status='approved').values_list('tags', flat=True):
        if isinstance(tag_list, list):
            for t in tag_list:
                counts[t] = counts.get(t, 0) + 1
    total = Post.objects.filter(status='approved').count()
    return counts, total

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

    featured = request.GET.get('featured', '') == '1'
    setting = KeywordSetting.objects.first()
    keywords = [k.strip() for k in setting.keywords.split(",") if k.strip()] if setting else []

    if featured and keywords:
        from django.db.models import Case, When, Value, BooleanField
        keyword_q = Q()
        for kw in keywords:
            keyword_q |= Q(title__icontains=kw) | Q(summary__icontains=kw) | Q(raw_content__icontains=kw)
        queryset = queryset.annotate(
            is_featured=Case(
                When(keyword_q, then=Value(True)),
                default=Value(False),
                output_field=BooleanField()
            )
        )
        if sort == 'newest':
            queryset = queryset.order_by('-is_featured', '-sort_date')
        else:
            queryset = queryset.order_by('-is_featured', 'sort_date')
    else:
        if sort == 'newest':
            queryset = queryset.order_by('-sort_date')
        else:
            queryset = queryset.order_by('sort_date')

    paginator = Paginator(queryset, 20)
    page_obj = paginator.get_page(page_num)
    
    posts = list(page_obj.object_list)
    # Reuse setting and keywords to avoid double DB queries
    if keywords:
        for post in posts:
            post.matched_keyword = None
            title = (post.title or "").lower()
            summary = (post.summary or "").lower()
            raw = (post.raw_content or "").lower()
            tags_str = " ".join(post.tags or []).lower()
            for kw in keywords:
                kw_lower = kw.lower()
                if kw_lower in title or kw_lower in summary or kw_lower in raw or kw_lower in tags_str:
                    post.matched_keyword = kw
                    break
    else:
        for post in posts:
            post.matched_keyword = None
    
    all_tags = get_all_tags()
    tag_counts, total_articles = get_tag_counts()

    from apps.sources.models import Source
    from apps.sources.management.commands.seed_sources import SEED_SOURCES
    seeded_names = [s['name'] for s in SEED_SOURCES]
    all_sources = Source.objects.filter(name__in=seeded_names).order_by('name')

    context = {
        'posts': posts,
        'page': page_num,
        'total_pages': paginator.num_pages,
        'all_tags': all_tags,
        'tag_counts': tag_counts,
        'total_articles': total_articles,
        'filtered_count': paginator.count,
        'all_sources': all_sources,
        'active_q': q,
        'active_tag': tag,
        'active_sort': sort,
        'active_source': source_id,
        'active_start_date': start_date,
        'active_end_date': end_date,
        'active_featured': featured,
        'active_page': 'feed'
    }
    
    if request.GET.get('ajax') == '1' or request.headers.get('x-requested-with') == 'XMLHttpRequest':
        from django.template.loader import render_to_string
        html = render_to_string('frontend/posts_fragment.jinja', context, request=request)
        return JsonResponse({
            'html': html,
            'page': page_num,
            'total_pages': paginator.num_pages,
            'total_count': paginator.count,
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
            posts = list(queryset.order_by('-published_at', '-fetched_at'))
            annotate_matched_keywords(posts)

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

