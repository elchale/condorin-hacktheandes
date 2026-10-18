def test_landing_shows_the_condorin_logo(client):
    resp = client.get('/')
    assert resp.status_code == 200
    html = resp.content.decode()
    assert 'brand/logo.png' in html
    assert 'Ojo de Cóndor' in html


def test_healthz(client):
    resp = client.get('/healthz/')
    assert resp.status_code == 200
    assert resp.json() == {'status': 'ok'}
