from django.db import models

class SavedPost(models.Model):
    """
    Maps an anonymous session token to a saved post ID.
    """
    token = models.CharField(max_length=255, db_index=True)
    post_id = models.IntegerField()  # Assuming Post is in another app, we just store the ID or we can import the Post model. We'll use IntegerField to decouple if Post isn't available in this context.
    saved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('token', 'post_id')
        db_table = 'saved_posts'

    def __str__(self):
        return f"Token {self.token} -> Post {self.post_id}"
