"""coach_logic_learner 測試：純函式統計（配速級距/質量課分類/賽後恢復週）用真實邏輯測，
LLM 呼叫與 Firestore 寫入用假物件 mock 呼叫時機與寫入邏輯，不測 LLM 輸出品質本身。
"""
import json
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import coach_logic_learner as learner


# ── extract_group_paces ──────────────────────────────────────────────

def test_extract_group_paces_letter_plus_group_suffix():
    text = "S組 保力達 乳酸閾值訓練(啊華、David)(300+200)*8 300m P’72-70s R100m60s"
    paces = learner.extract_group_paces(text)
    assert paces["S"] == 71.0


def test_extract_group_paces_bare_letter_after_quote_before_chinese():
    text = "R100m60s200m P’44-46s R2‘A 保力達啤酒 乳酸閾值訓練(修哥)(300+200)*8 300m P’76-78s"
    paces = learner.extract_group_paces(text)
    assert paces["A"] == 77.0


def test_extract_group_paces_multiple_groups_in_order():
    text = (
        "S組(啊華)300m P’72-70s\n"
        "Ｂ組(Amy)300m P’86-84s\n"
        "Ｃ組(威葳)300m P’88-86s"
    )
    paces = learner.extract_group_paces(text)
    assert paces == {"S": 71.0, "B": 85.0, "C": 87.0}


def test_extract_group_paces_ignores_percentage_pace():
    # 全力衝刺速度百分比（P'60-70%）不是秒數配速，不該被誤判成分組配速
    text = "S組(啊華) ST P’60-70%"
    assert learner.extract_group_paces(text) == {}


def test_extract_group_paces_no_groups_returns_empty():
    assert learner.extract_group_paces("小明 10-12k FR'") == {}
    assert learner.extract_group_paces(None) == {}
    assert learner.extract_group_paces("") == {}


def test_extract_group_paces_keeps_first_occurrence_only():
    text = "S組(啊華)300m P’72-70s\nS組重複(另一段)300m P’50-40s"
    paces = learner.extract_group_paces(text)
    assert paces["S"] == 71.0  # 只取第一次出現


# ── pace_gap_by_tier ──────────────────────────────────────────────────

def test_pace_gap_by_tier_computes_adjacent_diffs():
    weeks = [{
        "week_start": "2024-09-16",
        "D4": "S組(啊華)300m P’72-70s\nＡ組(修哥)300m P’76-78s\nＢ組(Amy)300m P’86-84s",
    }]
    result = learner.pace_gap_by_tier(weeks)
    assert result["S→A"]["n_samples"] == 1
    assert result["S→A"]["avg"] == 6.0  # A(77) - S(71)
    assert result["A→B"]["n_samples"] == 1
    assert result["A→B"]["avg"] == 8.0  # B(85) - A(77)
    assert result["B→C"]["n_samples"] == 0
    assert result["B→C"]["avg"] is None


def test_pace_gap_by_tier_skips_weeks_without_letter_groups():
    # 2025 之後姓名+時間帶分組的週，沒有字母標題，自然不貢獻樣本（非 bug）
    weeks = [{"week_start": "2026-06-15", "D4": "小明\n12-14k FR'"}]
    result = learner.pace_gap_by_tier(weeks)
    assert all(v["n_samples"] == 0 for v in result.values())


def test_pace_gap_by_tier_aggregates_across_weeks():
    week_a = {"week_start": "2024-09-02", "D4": "S組(啊華)300m P’72-70s\nＡ組(修哥)300m P’76-78s"}
    week_b = {"week_start": "2024-09-09", "D4": "S組(啊華)300m P’60-58s\nＡ組(修哥)300m P’66-64s"}
    result = learner.pace_gap_by_tier([week_a, week_b])
    assert result["S→A"]["n_samples"] == 2


# ── classify_quality_type ───────────────────────────────────────────

def test_classify_quality_type_400_interval():
    assert learner.classify_quality_type("400*12 P'110-112 R200m2'") == "400 定量間歇"


def test_classify_quality_type_800_interval():
    assert learner.classify_quality_type("800*5 P'106-110 r2'") == "800 定量間歇"


def test_classify_quality_type_1000_to_1200_bucket():
    assert learner.classify_quality_type("1000*3 P'94-96 R200m3'") == "1000-1200 長間歇"
    assert learner.classify_quality_type("1200*3 P'104-116") == "1000-1200 長間歇"


def test_classify_quality_type_2000_plus():
    assert learner.classify_quality_type("2000*2 P'110-144") == "2000+ 超長間歇"


def test_classify_quality_type_combo_pyramid_takes_priority():
    # 即使組合裡含 300/200，優先判為組合金字塔，不落入單一距離分類
    assert learner.classify_quality_type("(300+200)*8 300m P'72-70s 200m P'44-46s") == "組合金字塔"


def test_classify_quality_type_fartlek_keyword():
    assert learner.classify_quality_type("法特雷克 30-36分鐘跑60秒 @P'85%以上") == "法特雷克"


def test_classify_quality_type_no_interval_pattern_is_other():
    assert learner.classify_quality_type("小明 12-14k FR'") == learner.QUALITY_TYPE_OTHER


def test_classify_quality_type_none_or_empty_returns_none():
    assert learner.classify_quality_type(None) is None
    assert learner.classify_quality_type("") is None


# ── quality_type_distribution ──────────────────────────────────────

def test_quality_type_distribution_counts_and_percentages():
    weeks = [
        {"D4": "400*12 P'110-112"},
        {"D4": "400*10 P'112-114"},
        {"D4": "800*5 P'106-110"},
        {"D4": "小明 FR'"},
    ]
    result = learner.quality_type_distribution(weeks)
    assert result["total_weeks_classified"] == 4
    assert result["by_type"]["400 定量間歇"]["weeks"] == 2
    assert result["by_type"]["400 定量間歇"]["pct"] == 50.0


def test_quality_type_distribution_prefers_質量日_field_over_d4():
    weeks = [{"質量日": "D3", "D3": "400*12 P'110-112", "D4": "小明 Rest"}]
    result = learner.quality_type_distribution(weeks)
    assert result["by_type"]["400 定量間歇"]["weeks"] == 1


def test_quality_type_distribution_empty_weeks():
    result = learner.quality_type_distribution([])
    assert result == {"total_weeks_classified": 0, "by_type": {}}


# ── post_race_recovery_week_lengths ─────────────────────────────────

def test_post_race_recovery_detects_single_marked_week():
    weeks = [
        {"D4": "400*12 P'110-112"},
        {"D4": "小明 選擇性訓練"},
        {"D4": "400*12 P'110-112"},
    ]
    result = learner.post_race_recovery_week_lengths(weeks)
    assert result["samples_weeks"] == [1]
    assert result["n_samples"] == 1


def test_post_race_recovery_detects_consecutive_streak():
    weeks = [
        {"D4": "娛樂課程"},
        {"D4": "免評量"},
        {"D4": "400*12 P'110-112"},
    ]
    result = learner.post_race_recovery_week_lengths(weeks)
    assert result["samples_weeks"] == [2]


def test_post_race_recovery_trailing_streak_still_recorded():
    # 資料尾端仍在恢復期（還沒結束）也要記一筆，不能因為沒「結束」就漏掉
    weeks = [{"D4": "400*12"}, {"D4": "選擇性訓練"}]
    result = learner.post_race_recovery_week_lengths(weeks)
    assert result["samples_weeks"] == [1]


def test_post_race_recovery_no_markers_empty_result():
    weeks = [{"D4": "400*12 P'110-112"}]
    result = learner.post_race_recovery_week_lengths(weeks)
    assert result == {"samples_weeks": [], "avg_weeks": None, "n_samples": 0}


def test_post_race_recovery_checks_weekend_field_too():
    weeks = [{"D4": "400*12", "週末訓練": "小明 娛樂"}]
    result = learner.post_race_recovery_week_lengths(weeks)
    assert result["n_samples"] == 1


# ── compute_stats ────────────────────────────────────────────────────

def test_compute_stats_combines_all_three_and_metadata():
    weeks = [
        {"week_start": "2026-06-29", "D4": "400*12 P'110-112"},
        {"week_start": "2026-07-06", "D4": "小明 選擇性訓練"},
    ]
    stats = learner.compute_stats(weeks)
    assert stats["n_weeks_analyzed"] == 2
    assert stats["latest_week_start"] == "2026-07-06"
    assert "pace_gap_by_tier" in stats
    assert "quality_type_distribution" in stats
    assert "post_race_recovery_week_lengths" in stats


def test_compute_stats_empty_weeks():
    stats = learner.compute_stats([])
    assert stats["n_weeks_analyzed"] == 0
    assert stats["latest_week_start"] is None


# ── _parse_llm_json ──────────────────────────────────────────────────

def test_parse_llm_json_valid():
    payload = {"logic_summary": ["a"], "outlook": {"weeks": []}}
    result = learner._parse_llm_json(json.dumps(payload, ensure_ascii=False))
    assert result == payload


def test_parse_llm_json_strips_markdown_fence():
    payload = {"logic_summary": ["a"], "outlook": {}}
    text = "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"
    assert learner._parse_llm_json(text) == payload


def test_parse_llm_json_invalid_json_returns_empty_dict():
    assert learner._parse_llm_json("這不是 JSON") == {}


def test_parse_llm_json_missing_required_keys_returns_empty_dict():
    assert learner._parse_llm_json(json.dumps({"logic_summary": ["a"]})) == {}


def test_parse_llm_json_empty_text_returns_empty_dict():
    assert learner._parse_llm_json("") == {}
    assert learner._parse_llm_json(None) == {}


# ── generate_logic_update：mock Anthropic client，測呼叫時機不測輸出品質 ──

class _FakeContentBlock:
    """比照真實 Anthropic SDK content block 形狀（有 type，text 可能是 None）。"""

    def __init__(self, text, block_type="text"):
        self.text = text
        self.type = block_type


def _install_fake_ai_analyzer(monkeypatch, response_text, client_present=True,
                               with_thinking_block=False, stop_reason="end_turn"):
    calls = {}

    class _FakeMessages:
        def create(self, **kwargs):
            calls["kwargs"] = kwargs
            content = []
            if with_thinking_block:
                # claude-sonnet-5 預設吐的第一個 block：type="thinking"、text=None
                content.append(_FakeContentBlock(None, block_type="thinking"))
            content.append(_FakeContentBlock(response_text, block_type="text"))
            return types.SimpleNamespace(content=content, stop_reason=stop_reason)

    class _FakeClient:
        messages = _FakeMessages()

    fake_ai = types.ModuleType("ai_analyzer")
    fake_ai._get_client = (lambda: _FakeClient()) if client_present else (lambda: None)
    monkeypatch.setitem(sys.modules, "ai_analyzer", fake_ai)
    return calls


def test_generate_logic_update_no_weeks_skips_llm_call(monkeypatch):
    calls = _install_fake_ai_analyzer(monkeypatch, "{}")
    result = learner.generate_logic_update({}, [])
    assert result == {}
    assert calls == {}  # 沒週資料，根本不該打 LLM


def test_generate_logic_update_no_client_returns_empty(monkeypatch):
    _install_fake_ai_analyzer(monkeypatch, "{}", client_present=False)
    weeks = [{"week_start": "2026-07-06", "D4": "小明 選擇性訓練"}]
    result = learner.generate_logic_update({"n_weeks_analyzed": 1}, weeks)
    assert result == {}


def test_generate_logic_update_calls_client_with_expected_model_and_parses_response(monkeypatch):
    payload = {
        "logic_summary": ["重點1", "重點2", "重點3"],
        "outlook": {"generated_at": "2026-07-20", "note": "n", "weeks": []},
    }
    calls = _install_fake_ai_analyzer(monkeypatch, json.dumps(payload, ensure_ascii=False))
    weeks = [{"week_start": "2026-07-06", "D4": "小明 選擇性訓練"}]
    stats = learner.compute_stats(weeks)

    result = learner.generate_logic_update(stats, weeks)

    assert result == payload
    assert calls["kwargs"]["model"] == learner.MODEL
    assert "小明" in calls["kwargs"]["messages"][0]["content"]


def test_generate_logic_update_skips_leading_thinking_block(monkeypatch):
    # 回歸測試：claude-sonnet-5 預設先吐一個 thinking block（.text=None），
    # 2026-07-10 首跑時程式碼誤讀 content[0].text 拿到 None，靜默回空 dict。
    payload = {"logic_summary": ["a", "b", "c"], "outlook": {"weeks": []}}
    _install_fake_ai_analyzer(
        monkeypatch, json.dumps(payload, ensure_ascii=False), with_thinking_block=True,
    )
    weeks = [{"week_start": "2026-07-06", "D4": "小明 選擇性訓練"}]
    result = learner.generate_logic_update(learner.compute_stats(weeks), weeks)
    assert result == payload


def test_generate_logic_update_llm_exception_returns_empty(monkeypatch):
    class _BoomMessages:
        def create(self, **kwargs):
            raise RuntimeError("network down")

    class _FakeClient:
        messages = _BoomMessages()

    fake_ai = types.ModuleType("ai_analyzer")
    fake_ai._get_client = lambda: _FakeClient()
    monkeypatch.setitem(sys.modules, "ai_analyzer", fake_ai)

    weeks = [{"week_start": "2026-07-06", "D4": "小明 選擇性訓練"}]
    result = learner.generate_logic_update(learner.compute_stats(weeks), weeks)
    assert result == {}


# ── maybe_relearn：mock Firestore，測觸發條件與寫入邏輯 ──────────────

class _FakeSnap:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data
        self.exists = True

    def to_dict(self):
        return dict(self._data)


class _FakeMissingSnap:
    exists = False

    def to_dict(self):
        return {}


class _FakeDocRef:
    def __init__(self, store, coll, doc_id):
        self._store = store
        self._coll = coll
        self._doc_id = doc_id

    def get(self):
        data = self._store.get(self._coll, {}).get(self._doc_id)
        if data is None:
            return _FakeMissingSnap()
        return _FakeSnap(self._doc_id, data)

    def set(self, data, merge=False):
        coll = self._store.setdefault(self._coll, {})
        if merge and self._doc_id in coll:
            coll[self._doc_id].update(data)
        else:
            coll[self._doc_id] = dict(data)


class _FakeQuery:
    def __init__(self, snaps):
        self._snaps = snaps

    def order_by(self, field, direction=None):
        reverse = "DESC" in str(direction or "").upper()
        return _FakeQuery(sorted(
            self._snaps, key=lambda s: s.to_dict().get(field, ""), reverse=reverse))

    def limit(self, n):
        return _FakeQuery(self._snaps[:n])

    def stream(self):
        return list(self._snaps)


class _FakeCollectionRef:
    def __init__(self, store, name):
        self._store = store
        self._name = name

    def document(self, doc_id):
        return _FakeDocRef(self._store, self._name, doc_id)

    def stream(self):
        return [_FakeSnap(doc_id, data) for doc_id, data in self._store.get(self._name, {}).items()]

    def order_by(self, field, direction=None):
        return _FakeQuery(self.stream()).order_by(field, direction=direction)


class _FakeDB:
    def __init__(self, store):
        self._store = store

    def collection(self, name):
        return _FakeCollectionRef(self._store, name)


def _install_fake_firebase(monkeypatch, store):
    fake_fb = types.ModuleType("firebase_client")
    fake_fb._init = lambda: _FakeDB(store)
    monkeypatch.setitem(sys.modules, "firebase_client", fake_fb)


def test_maybe_relearn_no_coach_history_returns_false(monkeypatch):
    _install_fake_firebase(monkeypatch, {})
    assert learner.maybe_relearn() is False


def test_maybe_relearn_skips_llm_when_latest_week_unchanged(monkeypatch):
    store = {
        "coach_history": {"2026-07-06": {"week_start": "2026-07-06", "source": "firebase"}},
        "_meta": {"coach_logic_state": {"based_on_latest_week": "2026-07-06"}},
    }
    _install_fake_firebase(monkeypatch, store)
    called = {"n": 0}

    def fake_gen(stats, weeks):
        called["n"] += 1
        return {}

    monkeypatch.setattr(learner, "generate_logic_update", fake_gen)
    assert learner.maybe_relearn() is False
    assert called["n"] == 0  # 沒新週，LLM 呼叫要錢，不該打


def test_maybe_relearn_no_full_scan_when_latest_week_unchanged(monkeypatch):
    """沒新週時不准全掃 coach_history（全掃 × 每 5 分鐘 poll 會把 Firestore
    Spark 免費 50k reads/日 打爆）。"""
    store = {
        "coach_history": {"2026-07-06": {"week_start": "2026-07-06", "source": "firebase"}},
        "_meta": {"coach_logic_state": {"based_on_latest_week": "2026-07-06"}},
    }
    _install_fake_firebase(monkeypatch, store)

    def boom(db):
        raise AssertionError("沒新週不該呼叫 _fetch_coach_history_weeks 全掃")

    monkeypatch.setattr(learner, "_fetch_coach_history_weeks", boom)
    assert learner.maybe_relearn() is False


def test_maybe_relearn_triggers_and_writes_on_new_week(monkeypatch):
    store = {
        "coach_history": {
            "2026-06-29": {"week_start": "2026-06-29", "source": "firebase"},
            "2026-07-06": {"week_start": "2026-07-06", "source": "firebase"},
        },
        "_meta": {"coach_logic_state": {"based_on_latest_week": "2026-06-29"}},
    }
    _install_fake_firebase(monkeypatch, store)
    fake_result = {
        "logic_summary": ["a", "b", "c"],
        "outlook": {"generated_at": "2026-07-10", "note": "n", "weeks": []},
    }
    monkeypatch.setattr(learner, "generate_logic_update", lambda stats, weeks: fake_result)

    assert learner.maybe_relearn() is True

    written = store["_meta"]["coach_logic"]
    assert written["logic_summary"] == ["a", "b", "c"]
    assert written["based_on_latest_week"] == "2026-07-06"
    assert "stats" in written
    assert store["_meta"]["coach_logic_state"]["based_on_latest_week"] == "2026-07-06"


def test_maybe_relearn_llm_failure_does_not_update_state_or_output(monkeypatch):
    store = {"coach_history": {"2026-07-06": {"week_start": "2026-07-06", "source": "firebase"}}}
    _install_fake_firebase(monkeypatch, store)
    monkeypatch.setattr(learner, "generate_logic_update", lambda stats, weeks: {})

    assert learner.maybe_relearn() is False
    assert "coach_logic" not in store.get("_meta", {})
    assert "coach_logic_state" not in store.get("_meta", {})


def test_maybe_relearn_force_ignores_unchanged_state(monkeypatch):
    store = {
        "coach_history": {"2026-07-06": {"week_start": "2026-07-06", "source": "firebase"}},
        "_meta": {"coach_logic_state": {"based_on_latest_week": "2026-07-06"}},
    }
    _install_fake_firebase(monkeypatch, store)
    called = {"n": 0}

    def fake_gen(stats, weeks):
        called["n"] += 1
        return {"logic_summary": ["x"], "outlook": {}}

    monkeypatch.setattr(learner, "generate_logic_update", fake_gen)
    assert learner.maybe_relearn(force=True) is True
    assert called["n"] == 1


def test_maybe_relearn_excludes_gap_rows_from_latest_week(monkeypatch):
    store = {
        "coach_history": {
            "2026-06-29": {"week_start": "2026-06-29", "source": "firebase"},
            "2026-07-13": {"week_start": "2026-07-13", "source": "GAP"},
        },
    }
    _install_fake_firebase(monkeypatch, store)
    monkeypatch.setattr(
        learner, "generate_logic_update",
        lambda stats, weeks: {"logic_summary": ["x"], "outlook": {}},
    )
    assert learner.maybe_relearn() is True
    assert store["_meta"]["coach_logic"]["based_on_latest_week"] == "2026-06-29"


def test_maybe_relearn_firestore_exception_returns_false(monkeypatch):
    fake_fb = types.ModuleType("firebase_client")

    def _boom():
        raise RuntimeError("firestore down")

    fake_fb._init = _boom
    monkeypatch.setitem(sys.modules, "firebase_client", fake_fb)
    assert learner.maybe_relearn() is False
