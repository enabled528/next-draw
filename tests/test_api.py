from fastapi.testclient import TestClient
from next_draw.api import create_app


def test_api_validates_games_and_persists_a_finished_job(tmp_path):
    class Service:
        def run(self, game, progress, check):
            progress('history', '正在获取数据'); progress('prediction', '正在预测')
            return {'game': game, 'front': [1, 2, 3, 4, 5, 6], 'back': [7], 'score': 80}
    with TestClient(create_app(data_dir=tmp_path, service=Service())) as client:
        assert client.get('/api/health').json()['status'] == 'ok'
        assert client.post('/api/predictions', json={'game': '../private', 'request_id': 'test-request'}).status_code == 422
        submitted = client.post('/api/predictions', json={'game': 'ssq', 'request_id': 'test-request'}).json()
        assert client.post('/api/predictions', json={'game': 'ssq', 'request_id': 'test-request'}).json()['id'] == submitted['id']
        import time
        for _ in range(100):
            result = client.get('/api/jobs/' + submitted['id']).json()
            if result['status'] == 'complete': break
            time.sleep(.01)
        assert result['result']['back'] == [7]
        assert result['events'][-1]['stage'] == 'complete'
        assert client.get('/api/jobs/not-an-id').status_code == 404


def test_failed_real_selector_is_not_replaced_by_fake_success(tmp_path):
    class Service:
        def run(self, game, progress, check):
            progress('laya', '正在比较候选'); raise RuntimeError('Laya unavailable')
    with TestClient(create_app(data_dir=tmp_path, service=Service())) as client:
        job = client.post('/api/predictions', json={'game': 'ssq', 'request_id': 'test-failure'}).json()
        import time
        for _ in range(100):
            result = client.get('/api/jobs/' + job['id']).json()
            if result['status'] == 'failed': break
            time.sleep(.01)
        assert result['result'] is None and 'Laya' in result['error']
