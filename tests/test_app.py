import pytest
from werkzeug.security import generate_password_hash
from app import create_app
from app.extensions import db
from app.models import Admin, Dapur, Menu, Pelanggan, Pesanan


@pytest.fixture
def app(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    application = create_app()
    application.config["TESTING"] = True

    with application.app_context():
        db.create_all()
        db.session.add(Admin(nama_admin="admin", kata_laluan=generate_password_hash("admin123")))
        db.session.add(Dapur(nama_pengguna="dapur", kata_laluan=generate_password_hash("dapur123"), status=True))
        db.session.add(Dapur(nama_pengguna="inactive", kata_laluan=generate_password_hash("dapur123"), status=False))
        db.session.add(Menu(nama_minuman="Teh Tarik", harga=3.50, kategori="Panas", status_menu=True))
        db.session.commit()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def test_inactive_kitchen_cannot_login(client):
    res = client.post("/login", data={"role": "dapur", "username": "inactive", "password": "dapur123"})
    assert res.status_code == 200
    assert b"tidak aktif" in res.data


def test_customer_order_takeaway_and_status_api(client, app):
    with app.app_context():
        drink_id = Menu.query.first().id_menu

    client.get("/?table=A3")
    res = client.post("/order", data={
        f"qty_{drink_id}": "2",
        f"notes_{drink_id}": "Kurang manis",
        "jenis_pesanan": "Takeaway",
    }, follow_redirects=False)
    assert res.status_code == 302

    with app.app_context():
        cust = Pelanggan.query.first()
        assert cust.no_meja == "A3"
        assert cust.jenis_pesanan == "Takeaway"
        customer_id = cust.id_pelanggan

    api_res = client.get(f"/api/status/{customer_id}")
    assert api_res.status_code == 200
    payload = api_res.get_json()
    assert len(payload["orders"]) == 1
    assert payload["orders"][0]["status"] == "Baru"


def test_kitchen_shows_completed_orders_for_today(client, app):
    with app.app_context():
        drink = Menu.query.first()
        cust = Pelanggan(no_meja="A1")
        db.session.add(cust)
        db.session.flush()
        order = Pesanan(id_pelanggan=cust.id_pelanggan, id_menu=drink.id_menu, kuantiti=1, status_pesanan="Selesai")
        db.session.add(order)
        db.session.commit()

    client.post("/login", data={"role": "dapur", "username": "dapur", "password": "dapur123"})
    res = client.get("/kitchen/orders")
    assert res.status_code == 200
    assert b'data-status="Selesai"' in res.data


def test_admin_edit_and_delete_menu(client, app):
    client.post("/login", data={"role": "admin", "username": "admin", "password": "admin123"})
    with app.app_context():
        drink_id = Menu.query.first().id_menu

    res = client.post(f"/admin/menu/{drink_id}/edit", data={
        "nama_minuman": "Teh Tarik Kaw",
        "kategori": "Panas",
        "harga": "4.00",
    }, follow_redirects=True)
    assert res.status_code == 200
    assert b"Teh Tarik Kaw" in res.data

    res = client.post(f"/admin/menu/{drink_id}/delete", follow_redirects=True)
    assert res.status_code == 200
    with app.app_context():
        assert Menu.query.get(drink_id) is None
