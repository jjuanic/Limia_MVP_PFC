from django.urls import path
from . import views

urlpatterns = [
    path("projects/", views.list_projects),
    path("projects/create/", views.create_project),
    path("projects/<int:project_id>/sync/", views.sync_project),
    path("projects/<int:project_id>/generate/", views.generate_test),
    path("projects/<int:project_id>/tests/", views.list_test_requests),
    path("pick-directory/", views.pick_directory),
]
