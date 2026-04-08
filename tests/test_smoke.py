from django.test import Client


def test_health_check_returns_200():
    client = Client()
    response = client.get("/health/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_admin_login_page_returns_200():
    client = Client()
    response = client.get("/admin/", follow=True)
    assert response.status_code == 200