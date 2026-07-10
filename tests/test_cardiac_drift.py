import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import intervals_client as ic


def _series(hr_fn, vel_fn=None, dur=1800, step=1):
    """造合成 stream：time / hr / velocity，每 step 秒一點。"""
    times = list(range(0, dur, step))
    hrs = [hr_fn(t) for t in times]
    vels = [vel_fn(t) for t in times] if vel_fn else None
    return times, hrs, vels


def test_steady_run_with_drift():
    # 暖身爬升後，前半 150 / 後半 160，配速恆定 → drift ≈ +10
    def hr(t):
        if t < 300:
            return 100 + int((t / 300) * 50)   # 100→150 暖身
        return 150 if t < 1050 else 160          # 穩態前半/後半
    times, hrs, vels = _series(hr, vel_fn=lambda t: 2.8)
    assert ic.compute_drift(times, hrs, vels) == 10


def test_no_drift_is_zero():
    times, hrs, vels = _series(lambda t: 155, vel_fn=lambda t: 2.8)
    assert ic.compute_drift(times, hrs, vels) == 0


def test_too_short_returns_none():
    # 只有 400 秒，穩態段不足 10 分鐘
    times, hrs, vels = _series(lambda t: 155, vel_fn=lambda t: 2.8, dur=400)
    assert ic.compute_drift(times, hrs, vels) is None


def test_intervals_excluded_by_pace_cv():
    # 配速大幅變動（間歇）→ CV 超標 → None，即使心率有飄
    def hr(t):
        return 150 if t < 1050 else 165
    def vel(t):
        return 4.5 if (t // 60) % 2 == 0 else 1.5   # 快慢交替
    times, hrs, vels = _series(hr, vel_fn=vel)
    assert ic.compute_drift(times, hrs, vels) is None


def test_warmup_spike_does_not_inflate_drift():
    # 暖身段心率異常高，但穩態 300 秒後完全平穩 → drift 應為 0（暖身被排除）
    def hr(t):
        if t < 300:
            return 180                # 暖身虛高
        return 158
    times, hrs, vels = _series(hr, vel_fn=lambda t: 2.8)
    assert ic.compute_drift(times, hrs, vels) == 0


def test_empty_input_returns_none():
    assert ic.compute_drift([], []) is None
    assert ic.compute_drift(None, None) is None


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} passed")
