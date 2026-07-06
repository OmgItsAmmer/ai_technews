from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

class EmailBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        if username is None:
            username = kwargs.get('email')
        
        try:
            # First try finding the user by email
            user = UserModel.objects.get(email=username)
        except UserModel.DoesNotExist:
            # Fall back to username
            try:
                user = UserModel.objects.get(username=username)
            except UserModel.DoesNotExist:
                # Run the password hasher check anyway to reduce timing attack vulnerability
                UserModel().set_password(password)
                return None
        
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
