import pytest


@pytest.mark.django_db
def test_admin_login_page(client):
    response = client.get("/admin/login/")
    assert response.status_code == 200
