import json
import math
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator
from .models import SavedPost

# Mock Post model or assume it's imported from another app
# from apps.posts.models import Post
# For now, if we don't have the Post model, we use a placeholder or assume it's in `apps.posts`
try:
    from apps.posts.models import Post
except ImportError:
    # Dummy Post class if not found
    class Post:
        objects = None

def feed_view(request):
    q = request.GET.get('q', '')
    tag = request.GET.get('tag', '')
    sort = request.GET.get('sort', 'newest')
    page_num = int(request.GET.get('page', 1))

    # Real implementation would query the Post model here
    # Example:
    # queryset = Post.objects.filter(status='approved')
    # if q: queryset = queryset.filter(Q(title__icontains=q) | Q(summary__icontains=q))
    # if tag: queryset = queryset.filter(tags__contains=[tag])
    # if sort == 'newest': queryset = queryset.order_by('-published_at')
    # else: queryset = queryset.order_by('published_at')
    # paginator = Paginator(queryset, 20)
    # page_obj = paginator.get_page(page_num)
    # all_tags = get_all_tags()
    
    # Placeholder for no-data branch:
    posts = []
    total_pages = 1
    all_tags = []

    context = {
        'posts': posts,
        'page': page_num,
        'total_pages': total_pages,
        'all_tags': all_tags,
        'active_q': q,
        'active_tag': tag,
        'active_sort': sort,
        'active_page': 'feed'
    }
    return render(request, 'frontend/feed.html', context)

def saved_view(request):
    token = request.GET.get('token', '')
    posts = []
    
    if token:
        saved_ids = SavedPost.objects.filter(token=token).values_list('post_id', flat=True)
        if saved_ids:
            # posts = Post.objects.filter(id__in=saved_ids, status='approved').order_by('-published_at')
            pass

    context = {
        'posts': posts,
        'token': token,
        'active_page': 'saved'
    }
    return render(request, 'frontend/saved.html', context)

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
