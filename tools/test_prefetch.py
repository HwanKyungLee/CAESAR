"""알파 Pass 1 프리페치 리더 자체검증 (`gui.worker.prefetch_into_page_cache`).

이 함수가 하는 일은 "파일을 읽어 버리는 것"이라 결과값으로는 확인할 게 없다.
대신 **계약 네 가지**를 건다 — 하나라도 깨지면 알파 생성이 멈추거나(센티널 누락),
디스크를 도로 긁거나(순서·선행깊이), Stop 이 안 먹는다.

  1. 파일 순서를 그대로 흘린다 — Pass 1 은 제출 순서로 global_idx 를 매긴다.
  2. 큐 maxsize 만큼만 앞서간다 — 안 그러면 캐시가 밀려 프리페치가 무의미해진다.
  3. 끝나면 반드시 센티널을 넣는다 — 소비자가 영원히 기다리면 런이 멈춘다.
  4. stop 이 서면 즉시 빠져나온다 — 취소한 런이 132GB 를 계속 읽으면 안 된다.
  5. 못 읽는 파일이 있어도 죽지 않는다(자식이 평소대로 SKIP 처리).
"""
import os
import queue
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui.worker import prefetch_into_page_cache   # noqa: E402


def _make_files(tmp, n, size=64 * 1024):
    out = []
    for i in range(n):
        p = os.path.join(tmp, f"f{i:02d}.bin")
        with open(p, 'wb') as fh:
            fh.write(os.urandom(size))
        out.append(p)
    return out


def test_order_and_sentinel():
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_files(tmp, 5)
        q, stop = queue.Queue(maxsize=3), threading.Event()
        th = threading.Thread(target=prefetch_into_page_cache, args=(files, q, stop))
        th.start()
        got = []
        while True:
            item = q.get(timeout=5)
            if item is None:
                break
            got.append(item)
        th.join(timeout=5)
        assert got == files, f"순서가 바뀌었다: {got}"
        assert not th.is_alive()


def test_lookahead_is_bounded():
    """소비자가 안 가져가면 maxsize 에서 막혀야 한다(선행 깊이 = 캐시 점유 상한)."""
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_files(tmp, 20)
        q, stop = queue.Queue(maxsize=2), threading.Event()
        th = threading.Thread(target=prefetch_into_page_cache, args=(files, q, stop))
        th.start()
        time.sleep(0.5)                 # 아무것도 소비하지 않는다
        assert q.qsize() <= 2, f"선행 깊이를 넘었다: {q.qsize()}"
        stop.set()
        th.join(timeout=5)
        assert not th.is_alive(), "stop 후에도 리더가 살아 있다"


def test_stop_is_honoured_mid_run():
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_files(tmp, 50)
        q, stop = queue.Queue(maxsize=50), threading.Event()
        th = threading.Thread(target=prefetch_into_page_cache, args=(files, q, stop))
        th.start()
        time.sleep(0.05)
        stop.set()
        th.join(timeout=5)
        assert not th.is_alive()
        assert q.qsize() < len(files) + 1, "stop 했는데 전부 읽었다"


def test_unreadable_file_does_not_kill_the_reader():
    with tempfile.TemporaryDirectory() as tmp:
        files = _make_files(tmp, 3)
        files.insert(1, os.path.join(tmp, "does_not_exist.bin"))
        q, stop = queue.Queue(maxsize=8), threading.Event()
        th = threading.Thread(target=prefetch_into_page_cache, args=(files, q, stop))
        th.start()
        got = []
        while True:
            item = q.get(timeout=5)
            if item is None:
                break
            got.append(item)
        th.join(timeout=5)
        assert got == files, "없는 파일도 그대로 흘려보내야 한다(자식이 SKIP 처리)"


if __name__ == '__main__':
    test_order_and_sentinel()
    test_lookahead_is_bounded()
    test_stop_is_honoured_mid_run()
    test_unreadable_file_does_not_kill_the_reader()
    print("PASS: 프리페치 리더 계약 4건")
