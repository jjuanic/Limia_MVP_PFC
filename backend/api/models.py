from django.db import models


class Project(models.Model):
    name = models.CharField(max_length=255)
    directory_path = models.CharField(max_length=1024)
    created_at = models.DateTimeField(auto_now_add=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.name


class TestRequest(models.Model):
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="test_requests"
    )
    natural_instruction = models.TextField()
    generated_cypress_code = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"[{self.project.name}] {self.natural_instruction[:60]}"
