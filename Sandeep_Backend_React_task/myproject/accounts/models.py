from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

class LogEntry(models.Model):
    command = models.CharField(max_length=255)
    approved = models.BooleanField(default=False)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.command} - {self.created_at}"

class LoginEntry(models.Model):
    username = models.CharField(max_length=255)
    login_time = models.DateTimeField(auto_now_add=True)
    success = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.username} - {self.login_time} - {'Success' if self.success else 'Failed'}"

class Topic(models.Model):
    name = models.CharField(max_length=255, unique=True)
    partitions = models.PositiveIntegerField(default=3)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    production = models.CharField(max_length=20, default="Inactive")
    consumption = models.CharField(max_length=20, default="Inactive")
    followers = models.IntegerField(default=0)
    observers = models.IntegerField(default=0)
    last_produced = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.name

class TopicRequest(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('DECLINED', 'Declined'),
    ]
    topic_name = models.CharField(max_length=255)
    partitions = models.PositiveIntegerField(default=3)
    requested_by = models.ForeignKey(User, on_delete=models.CASCADE)
    requested_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_requests')
    reviewed_at = models.DateTimeField(auto_now_add=True) #added by Sandeep
    # reviewed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.topic_name} - {self.status}"