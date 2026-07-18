from tasks.models import TaskKind, TaskStatus
from tasks.media_queue import MediaQueue
from tasks.store import TaskStore
from tasks.subtitle_queue import SubtitleQueue
import tempfile
import time
from pathlib import Path
from threading import Event


def test_task_store_creates_and_lists_tasks():
    store = TaskStore()
    task = store.create(
        kind=TaskKind.CONVERT,
        title='a.csv → XLSX',
        payload={'source': 'csv', 'target': 'xlsx'},
    )

    assert task.id
    assert task.kind == TaskKind.CONVERT
    assert task.status == TaskStatus.PENDING
    assert store.list()[0].id == task.id


def test_task_store_updates_task_status_and_logs():
    store = TaskStore()
    task = store.create(kind=TaskKind.MEDIA, title='抖音链接', payload={'link': 'https://v.douyin.com/example/'})

    updated = store.update(
        task.id,
        status=TaskStatus.RUNNING,
        logs=['开始解析'],
        result={'platform': 'douyin'},
    )

    assert updated is not None
    assert updated.status == TaskStatus.RUNNING
    assert updated.logs == ['开始解析']
    assert updated.result == {'platform': 'douyin'}


def test_task_store_returns_none_for_unknown_task():
    store = TaskStore()
    assert store.get('missing') is None
    assert store.update('missing', status=TaskStatus.FAILED) is None


def test_task_item_to_dict_returns_shallow_copies_for_mutable_fields():
    store = TaskStore()
    task = store.create(
        kind=TaskKind.CONVERT,
        title='copy check',
        payload={'source': 'csv'},
    )
    store.update(task.id, logs=['created'], result={'target': 'xlsx'})

    exported = task.to_dict()
    exported['payload']['source'] = 'mutated'
    exported['logs'].append('mutated')
    exported['result']['target'] = 'mutated'

    assert task.payload == {'source': 'csv'}
    assert task.logs == ['created']
    assert task.result == {'target': 'xlsx'}


def test_task_item_to_dict_redacts_sensitive_payload_fields():
    store = TaskStore()
    task = store.create(
        kind=TaskKind.MEDIA,
        title='cookie check',
        payload={
            'link': 'https://www.bilibili.com/video/BV1demo',
            'bilibiliCookie': 'SESSDATA=secret',
            'nested': {'accessToken': 'token-secret'},
        },
    )

    exported = task.to_dict()

    assert exported['payload']['link'] == 'https://www.bilibili.com/video/BV1demo'
    assert exported['payload']['bilibiliCookie'] == '[REDACTED]'
    assert exported['payload']['nested']['accessToken'] == '[REDACTED]'
    assert task.payload['bilibiliCookie'] == 'SESSDATA=secret'


def test_task_store_update_can_clear_error_and_result():
    store = TaskStore()
    task = store.create(kind=TaskKind.MEDIA, title='media', payload={})
    store.update(task.id, result={'platform': 'douyin'}, error='failed once')

    updated = store.update(task.id, result=None, error=None)

    assert updated is not None
    assert updated.result is None
    assert updated.error is None


def test_task_store_patch_result_preserves_download_result_fields():
    store = TaskStore()
    task = store.create(kind=TaskKind.MEDIA, title='media', payload={})
    store.update(task.id, status=TaskStatus.COMPLETED, result={
        'outputPath': '/tmp/video.mp4',
        'subtitleJob': {'status': 'pending'},
    })

    updated = store.patch_result(task.id, {'subtitleJob': {'status': 'running'}})

    assert updated is not None
    assert updated.result['outputPath'] == '/tmp/video.mp4'
    assert updated.result['subtitleJob']['status'] == 'running'


def test_task_store_list_filters_by_kind():
    store = TaskStore()
    convert = store.create(kind=TaskKind.CONVERT, title='convert', payload={})
    media = store.create(kind=TaskKind.MEDIA, title='media', payload={})

    assert [task.id for task in store.list(kind=TaskKind.CONVERT)] == [convert.id]
    assert [task.id for task in store.list(kind=TaskKind.MEDIA)] == [media.id]


def test_task_store_clear_deletes_only_matching_kind():
    store = TaskStore()
    convert = store.create(kind=TaskKind.CONVERT, title='convert', payload={})
    media = store.create(kind=TaskKind.MEDIA, title='media', payload={})

    deleted_count = store.clear(kind=TaskKind.CONVERT)

    assert deleted_count == 1
    assert store.get(convert.id) is None
    assert store.get(media.id) is not None


def test_task_store_evicts_oldest_task_when_max_items_is_exceeded():
    store = TaskStore(max_items=2)
    first = store.create(kind=TaskKind.CONVERT, title='first', payload={})
    second = store.create(kind=TaskKind.MEDIA, title='second', payload={})
    third = store.create(kind=TaskKind.CONVERT, title='third', payload={})

    assert store.get(first.id) is None
    assert [task.id for task in store.list()] == [third.id, second.id]


def test_task_store_persists_completed_history():
    with tempfile.TemporaryDirectory() as tmp:
        storage = Path(tmp) / 'tasks.json'
        store = TaskStore(storage_path=storage)
        task = store.create(kind=TaskKind.CONVERT, title='persisted', payload={'source': 'csv'})
        store.update(task.id, status=TaskStatus.COMPLETED, result={'outputPath': '/tmp/a.json'})
        restored = TaskStore(storage_path=storage)
        loaded = restored.get(task.id)
        assert loaded is not None
        assert loaded.status == TaskStatus.COMPLETED
        assert loaded.result == {'outputPath': '/tmp/a.json'}


def test_task_store_persists_stage_and_progress():
    with tempfile.TemporaryDirectory() as tmp:
        storage = Path(tmp) / 'tasks.json'
        store = TaskStore(storage_path=storage)
        task = store.create(kind=TaskKind.MEDIA, title='progress', payload={})
        store.update(task.id, status=TaskStatus.RUNNING, stage='下载中', progress=42.5)
        loaded = TaskStore(storage_path=storage).get(task.id)
        assert loaded is not None
        # 运行中任务在服务重启后会正确标记为中断，不会继续伪装运行。
        assert loaded.status == TaskStatus.FAILED
        assert loaded.stage == '已中断'


def test_task_store_marks_only_background_subtitle_as_interrupted_after_restart():
    with tempfile.TemporaryDirectory() as tmp:
        storage = Path(tmp) / 'tasks.json'
        store = TaskStore(storage_path=storage)
        task = store.create(kind=TaskKind.MEDIA, title='video', payload={})
        store.update(task.id, status=TaskStatus.COMPLETED, stage='视频已下载', result={
            'outputPath': '/tmp/video.mp4',
            'subtitleJob': {'status': 'running'},
        })

        loaded = TaskStore(storage_path=storage).get(task.id)

        assert loaded is not None
        assert loaded.status == TaskStatus.COMPLETED
        assert loaded.result['outputPath'] == '/tmp/video.mp4'
        assert loaded.result['subtitleJob']['status'] == 'interrupted'


def _wait_until(predicate, timeout: float = 1.5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_media_queue_completes_video_before_starting_subtitle_hook():
    store = TaskStore()
    observed = []

    def success_hook(task_id, payload, result):
        current = store.get(task_id)
        observed.append((current.status, current.stage, result['outputPath']))

    queue = MediaQueue(
        store,
        lambda payload: {
            'success': True,
            'stdout': 'video ready',
            'stderr': '',
            'outputPath': '/tmp/video.mp4',
            'subtitleJob': {'status': 'pending'},
        },
        interval_seconds=0,
        success_hook=success_hook,
    )
    task_id = queue.submit([{'link': 'https://example.com/video'}])[0]['id']

    assert _wait_until(lambda: bool(observed))
    task = store.get(task_id)
    assert observed == [(TaskStatus.COMPLETED, '视频已下载', '/tmp/video.mp4')]
    assert task is not None and task.status == TaskStatus.COMPLETED


def test_subtitle_queue_updates_completed_video_without_reopening_main_task():
    store = TaskStore()
    task = store.create(kind=TaskKind.MEDIA, title='video', payload={})
    store.update(task.id, status=TaskStatus.COMPLETED, stage='视频已下载', result={
        'outputPath': '/tmp/video.mp4',
        'assets': {'cover': None, 'subtitles': [], 'subtitleDetails': []},
        'subtitleJob': {'status': 'pending', 'strategy': 'native-asr'},
    })
    queue = SubtitleQueue(store, lambda payload: {
        'status': 'completed',
        'message': '语音字幕识别完成，字幕文件已保存',
        'subtitles': ['/tmp/video_subtitle_asr.srt'],
        'subtitleDetails': [{'path': '/tmp/video_subtitle_asr.srt', 'source': 'speech-asr'}],
    })

    assert queue.submit(task.id, {'inputPath': '/tmp/video.mp4'})
    assert _wait_until(lambda: (store.get(task.id).result or {}).get('subtitleJob', {}).get('status') == 'completed')
    updated = store.get(task.id)
    assert updated is not None
    assert updated.status == TaskStatus.COMPLETED
    assert updated.stage == '视频已下载'
    assert updated.result['outputPath'] == '/tmp/video.mp4'
    assert updated.result['assets']['subtitles'] == ['/tmp/video_subtitle_asr.srt']


def test_video_result_is_openable_while_subtitle_worker_is_still_running():
    store = TaskStore()
    subtitle_started = Event()
    release_subtitle = Event()

    def subtitle_runner(payload):
        subtitle_started.set()
        release_subtitle.wait(timeout=1.5)
        return {
            'status': 'completed',
            'message': '字幕识别完成',
            'subtitles': ['/tmp/video_subtitle_asr.srt'],
            'subtitleDetails': [],
        }

    subtitle_queue = SubtitleQueue(store, subtitle_runner)

    def enqueue_subtitle(task_id, payload, result):
        subtitle_queue.submit(task_id, {'inputPath': result['outputPath']})

    media_queue = MediaQueue(
        store,
        lambda payload: {
            'success': True,
            'stdout': 'video ready',
            'stderr': '',
            'outputPath': '/tmp/video.mp4',
            'assets': {'cover': None, 'subtitles': [], 'subtitleDetails': []},
            'subtitleJob': {'status': 'pending'},
        },
        interval_seconds=0,
        success_hook=enqueue_subtitle,
    )
    task_id = media_queue.submit([{'link': 'https://example.com/video'}])[0]['id']

    assert subtitle_started.wait(timeout=1.5)
    while_subtitle_runs = store.get(task_id)
    assert while_subtitle_runs is not None
    assert while_subtitle_runs.status == TaskStatus.COMPLETED
    assert while_subtitle_runs.result['outputPath'] == '/tmp/video.mp4'
    assert while_subtitle_runs.result['subtitleJob']['status'] == 'running'

    release_subtitle.set()
    assert _wait_until(lambda: (store.get(task_id).result or {}).get('subtitleJob', {}).get('status') == 'completed')


def test_task_store_clear_finished_keeps_active_tasks():
    store = TaskStore()
    active = store.create(kind=TaskKind.MEDIA, title='active', payload={})
    background = store.create(kind=TaskKind.MEDIA, title='subtitle running', payload={})
    finished = store.create(kind=TaskKind.MEDIA, title='finished', payload={})
    store.update(background.id, status=TaskStatus.COMPLETED, result={'subtitleJob': {'status': 'running'}})
    store.update(finished.id, status=TaskStatus.COMPLETED)

    assert store.clear_finished(TaskKind.MEDIA) == 1
    assert store.get(active.id) is not None
    assert store.get(background.id) is not None
    assert store.get(finished.id) is None


def test_task_store_delete_removes_only_requested_task():
    store = TaskStore()
    first = store.create(kind=TaskKind.MEDIA, title='first', payload={})
    second = store.create(kind=TaskKind.MEDIA, title='second', payload={})

    deleted = store.delete(first.id)

    assert deleted is first
    assert store.get(first.id) is None
    assert store.get(second.id) is not None
    assert store.delete('missing') is None


_TEST_FUNCTIONS = [
    test_task_store_creates_and_lists_tasks,
    test_task_store_updates_task_status_and_logs,
    test_task_store_returns_none_for_unknown_task,
    test_task_item_to_dict_returns_shallow_copies_for_mutable_fields,
    test_task_item_to_dict_redacts_sensitive_payload_fields,
    test_task_store_update_can_clear_error_and_result,
    test_task_store_patch_result_preserves_download_result_fields,
    test_task_store_list_filters_by_kind,
    test_task_store_clear_deletes_only_matching_kind,
    test_task_store_evicts_oldest_task_when_max_items_is_exceeded,
    test_task_store_persists_completed_history,
    test_task_store_persists_stage_and_progress,
    test_task_store_marks_only_background_subtitle_as_interrupted_after_restart,
    test_media_queue_completes_video_before_starting_subtitle_hook,
    test_subtitle_queue_updates_completed_video_without_reopening_main_task,
    test_video_result_is_openable_while_subtitle_worker_is_still_running,
    test_task_store_clear_finished_keeps_active_tasks,
    test_task_store_delete_removes_only_requested_task,
]


def load_tests(loader, tests, pattern):
    import unittest

    suite = unittest.TestSuite()
    for test_function in _TEST_FUNCTIONS:
        suite.addTest(unittest.FunctionTestCase(test_function))
    return suite
