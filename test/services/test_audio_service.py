# test/services/test_audio_service.py
#
# Testeamos: services/audio_service.py
# - _ttl_from_url           → extrae TTL de query params de URL de YouTube
# - pick_best_audio         → selecciona mejor formato de audio
# - _guess_audio_media_type → infiere MIME type desde URL y header
# - _ct_base                → extrae MIME base sin parámetros
# - is_cache_valid          → valida entry de cache por TTL
# - build_cache_entry       → construye entrada de cache
# - schedule_warm           → encola video_ids para warming (dedup, burst)
# - get_warm_burst          → retorna constante _WARM_BURST
# - _get_or_extract         → cache hit / miss / force
#

import time
import pytest
from unittest.mock import patch, MagicMock
from services.audio_service import (
    _ttl_from_url,
    pick_best_audio,
    _guess_audio_media_type,
    _ct_base,
    is_cache_valid,
    build_cache_entry,
    schedule_warm,
    get_warm_burst,
    _get_or_extract,
    URL_TTL,
    _WARM_BURST,
    _WARM_DEDUP_TTL,
)

# ════════════════════════════════════════════════════════
# _ttl_from_url
# ════════════════════════════════════════════════════════
class TestTtlFromUrl:
    def _url_with_expire(self, offset: int) -> str:
        exp = int(time.time()) + offset
        return f"https://rr1.sn-something.googlevideo.com/videoplayback?expire={exp}&other=x"

    def test_expire_param_returns_clamped_value(self):
        url = self._url_with_expire(3600)
        ttl = _ttl_from_url(url)
        # exp - now - 120 ≈ 3480, clamped a max 5400
        assert 60 <= ttl <= 90 * 60

    def test_expire_in_past_returns_minimum(self):
        url = self._url_with_expire(-500)
        ttl = _ttl_from_url(url)
        assert ttl == 60

    def test_x_goog_expires_param(self):
        url = "https://storage.googleapis.com/audio?x-goog-expires=3600&foo=bar"
        ttl = _ttl_from_url(url)
        assert 60 <= ttl <= 90 * 60

    def test_x_goog_expires_small_value_returns_minimum(self):
        url = "https://storage.googleapis.com/audio?x-goog-expires=50"
        ttl = _ttl_from_url(url)
        assert ttl == 60

    def test_no_known_params_returns_default(self):
        url = "https://example.com/audio.m4a"
        assert _ttl_from_url(url) == URL_TTL

    def test_malformed_url_returns_default(self):
        assert _ttl_from_url("not_a_url") == URL_TTL

    def test_expire_value_capped_at_90_minutes(self):
        url = self._url_with_expire(999999)
        ttl = _ttl_from_url(url)
        assert ttl == 90 * 60

    def test_empty_string_returns_default(self):
        assert _ttl_from_url("") == URL_TTL

# ════════════════════════════════════════════════════════
# pick_best_audio
# ════════════════════════════════════════════════════════
class TestPickBestAudio:
    def _fmt(self, vcodec, acodec, url="https://audio.example.com/track.webm"):
        return {"vcodec": vcodec, "acodec": acodec, "url": url}

    def test_picks_audio_only_format(self):
        info = {
            "formats": [
                self._fmt("avc1", "mp4a"),         # video+audio → skip
                self._fmt("none", "opus"),          # audio only → pick
            ]
        }
        url, fmt, diag = pick_best_audio(info)
        assert url == "https://audio.example.com/track.webm"
        assert fmt is not None
        assert diag["reason"] == "best_available"

    def test_prefers_last_audio_only_format(self):
        """reversed(fmts) → último en la lista original gana."""
        info = {
            "formats": [
                self._fmt("none", "opus", "https://low.example.com"),
                self._fmt("none", "opus", "https://high.example.com"),
            ]
        }
        url, _, _ = pick_best_audio(info)
        assert url == "https://high.example.com"

    def test_skips_format_without_url(self):
        info = {
            "formats": [
                {"vcodec": "none", "acodec": "opus", "url": None},
                self._fmt("none", "mp4a", "https://fallback.example.com"),
            ]
        }
        url, _, _ = pick_best_audio(info)
        assert url == "https://fallback.example.com"

    def test_skips_format_with_none_acodec(self):
        info = {
            "formats": [
                self._fmt("none", "none"),
                self._fmt("none", "mp4a", "https://good.example.com"),
            ]
        }
        url, _, _ = pick_best_audio(info)
        assert url == "https://good.example.com"

    def test_fallback_when_no_audio_only_format(self):
        info = {
            "formats": [self._fmt("avc1", "mp4a", "https://video.example.com")],
            "url": "https://direct.example.com",
        }
        url, fmt, diag = pick_best_audio(info)
        assert url == "https://direct.example.com"
        assert fmt is None
        assert diag["reason"] == "fallback"

    def test_empty_formats_returns_fallback(self):
        info = {"formats": [], "url": "https://direct.example.com"}
        url, fmt, diag = pick_best_audio(info)
        assert url == "https://direct.example.com"
        assert diag["reason"] == "fallback"

    def test_no_formats_key_returns_fallback(self):
        info = {"url": "https://direct.example.com"}
        url, _, diag = pick_best_audio(info)
        assert url == "https://direct.example.com"
        assert diag["reason"] == "fallback"

    def test_empty_info_returns_none_url(self):
        url, fmt, diag = pick_best_audio({})
        assert url is None
        assert fmt is None
        assert diag["reason"] == "fallback"

# ════════════════════════════════════════════════════════
# _guess_audio_media_type
# ════════════════════════════════════════════════════════
class TestGuessAudioMediaType:
    def test_uses_header_content_type_when_specific(self):
        result = _guess_audio_media_type("https://example.com/x", "audio/webm")
        assert result == "audio/webm"

    def test_ignores_octet_stream_header(self):
        result = _guess_audio_media_type("https://example.com/track.m4a", "application/octet-stream")
        assert result == "audio/mp4"

    def test_ignores_none_header(self):
        result = _guess_audio_media_type("https://example.com/track.webm", None)
        assert result == "audio/webm"

    def test_detects_m4a_from_url(self):
        result = _guess_audio_media_type("https://example.com/audio.m4a", None)
        assert result == "audio/mp4"

    def test_detects_mp4_from_url(self):
        result = _guess_audio_media_type("https://example.com/audio.mp4", None)
        assert result == "audio/mp4"

    def test_detects_webm_from_url(self):
        result = _guess_audio_media_type("https://example.com/audio.webm", None)
        assert result == "audio/webm"

    def test_detects_weba_from_url(self):
        result = _guess_audio_media_type("https://example.com/audio.weba", None)
        assert result == "audio/webm"

    def test_detects_mime_from_query_param(self):
        url = "https://rr1.googlevideo.com/audio?mime=audio%2Fwebm&other=x"
        result = _guess_audio_media_type(url, None)
        assert result == "audio/webm"

    def test_unknown_url_returns_wildcard(self):
        result = _guess_audio_media_type("https://example.com/stream", None)
        assert result == "audio/*"

# ════════════════════════════════════════════════════════
# _ct_base
# ════════════════════════════════════════════════════════
class TestCtBase:
    def test_strips_charset_param(self):
        assert _ct_base("audio/webm; codecs=opus") == "audio/webm"

    def test_returns_plain_type_unchanged(self):
        assert _ct_base("audio/mp4") == "audio/mp4"

    def test_none_returns_none(self):
        assert _ct_base(None) is None

    def test_empty_string_returns_none(self):
        assert _ct_base("") is None

    def test_multiple_params_strips_all(self):
        assert _ct_base("audio/webm; codecs=opus; charset=utf-8") == "audio/webm"

# ════════════════════════════════════════════════════════
# is_cache_valid
# ════════════════════════════════════════════════════════
class TestIsCacheValid:
    def _entry(self, age_seconds: int, ttl: int = URL_TTL) -> dict:
        now = time.time()
        return {"direct_url": "https://audio.example.com/x", "ts": now - age_seconds, "ttl": ttl}

    def test_fresh_entry_is_valid(self):
        assert is_cache_valid(self._entry(10), time.time()) is True

    def test_expired_entry_is_invalid(self):
        assert is_cache_valid(self._entry(URL_TTL + 1), time.time()) is False

    def test_entry_at_exact_ttl_is_invalid(self):
        # age == ttl → NOT < ttl
        entry = self._entry(URL_TTL)
        assert is_cache_valid(entry, time.time()) is False

    def test_none_entry_is_invalid(self):
        assert is_cache_valid(None, time.time()) is False

    def test_entry_without_direct_url_is_invalid(self):
        assert is_cache_valid({"ts": time.time(), "ttl": URL_TTL}, time.time()) is False

    def test_custom_ttl_respected(self):
        assert is_cache_valid(self._entry(500, ttl=1000), time.time()) is True
        assert is_cache_valid(self._entry(1001, ttl=1000), time.time()) is False

    def test_missing_ttl_falls_back_to_default(self):
        now = time.time()
        entry = {"direct_url": "https://x.com", "ts": now - 10}  # sin ttl
        assert is_cache_valid(entry, now) is True

# ════════════════════════════════════════════════════════
# build_cache_entry
# ════════════════════════════════════════════════════════
class TestBuildCacheEntry:
    def test_builds_correct_structure(self):
        now = time.time()
        url = "https://rr1.googlevideo.com/audio?expire=9999999999"
        info = {"title": "Creep"}
        entry = build_cache_entry(info, url, "pytubefix", now)

        assert entry["info"] == info
        assert entry["direct_url"] == url
        assert entry["client"] == "pytubefix"
        assert entry["ts"] == now
        assert "ttl" in entry

    def test_ttl_derived_from_url(self):
        now = time.time()
        exp = int(now) + 3600
        url = f"https://googlevideo.com/audio?expire={exp}"
        entry = build_cache_entry({}, url, "yt-dlp", now)
        # ttl debería ser aprox 3480 (3600 - 120), dentro de los límites
        assert 60 <= entry["ttl"] <= 90 * 60

    def test_url_without_expire_uses_default_ttl(self):
        entry = build_cache_entry({}, "https://example.com/audio.m4a", "pytubefix", time.time())
        assert entry["ttl"] == URL_TTL

# ════════════════════════════════════════════════════════
# schedule_warm
# ════════════════════════════════════════════════════════
class TestScheduleWarm:
    def setup_method(self):
        # Limpiamos el estado de inflight entre tests
        from services.audio_service import _WARM_INFLIGHT
        _WARM_INFLIGHT.clear()

    def test_does_nothing_when_warm_disabled(self):
        with patch("services.audio_service.WARM_ENABLED", False), \
             patch("services.audio_service._get_warm_executor") as mock_ex:
            schedule_warm(["vid1", "vid2"])
        mock_ex.assert_not_called()

    def test_does_nothing_with_empty_list(self):
        with patch("services.audio_service.WARM_ENABLED", True), \
             patch("services.audio_service._get_warm_executor") as mock_ex:
            schedule_warm([])
        mock_ex.assert_not_called()

    def test_submits_ids_when_enabled(self):
        mock_executor = MagicMock()
        with patch("services.audio_service.WARM_ENABLED", True), \
             patch("services.audio_service._get_warm_executor", return_value=mock_executor):
            schedule_warm(["vid1", "vid2"])
        assert mock_executor.submit.call_count == 2

    def test_deduplicates_ids(self):
        mock_executor = MagicMock()
        with patch("services.audio_service.WARM_ENABLED", True), \
             patch("services.audio_service._get_warm_executor", return_value=mock_executor):
            schedule_warm(["vid1", "vid1", "vid1"])
        assert mock_executor.submit.call_count == 1

    def test_respects_burst_limit(self):
        mock_executor = MagicMock()
        ids = [f"vid{i}" for i in range(_WARM_BURST + 10)]
        with patch("services.audio_service.WARM_ENABLED", True), \
             patch("services.audio_service._get_warm_executor", return_value=mock_executor):
            schedule_warm(ids)
        assert mock_executor.submit.call_count <= _WARM_BURST

    def test_dedup_ttl_prevents_resubmission(self):
        mock_executor = MagicMock()
        with patch("services.audio_service.WARM_ENABLED", True), \
             patch("services.audio_service._get_warm_executor", return_value=mock_executor):
            schedule_warm(["vid1"])
            schedule_warm(["vid1"])  # dentro de dedup TTL → ignorado
        assert mock_executor.submit.call_count == 1

    def test_allows_resubmission_after_dedup_ttl(self):
        mock_executor = MagicMock()
        past = time.time() - _WARM_DEDUP_TTL - 1
        from services import audio_service
        audio_service._WARM_INFLIGHT["vid1"] = past

        with patch("services.audio_service.WARM_ENABLED", True), \
             patch("services.audio_service._get_warm_executor", return_value=mock_executor):
            schedule_warm(["vid1"])
        assert mock_executor.submit.call_count == 1

    def test_filters_none_and_empty_ids(self):
        mock_executor = MagicMock()
        with patch("services.audio_service.WARM_ENABLED", True), \
             patch("services.audio_service._get_warm_executor", return_value=mock_executor):
            schedule_warm([None, "", "vid1"])
        assert mock_executor.submit.call_count == 1

# ════════════════════════════════════════════════════════
# get_warm_burst
# ════════════════════════════════════════════════════════
class TestGetWarmBurst:
    def test_returns_warm_burst_constant(self):
        assert get_warm_burst() == _WARM_BURST

# ════════════════════════════════════════════════════════
# _get_or_extract
# ════════════════════════════════════════════════════════
class TestGetOrExtract:
    def setup_method(self):
        from services import audio_service
        audio_service._cache.clear()

    def _make_entry(self, video_id: str, age: int = 10, ttl: int = URL_TTL) -> dict:
        now = time.time()
        return {
            "direct_url": f"https://audio.example.com/{video_id}",
            "info": {"title": "Test"},
            "client": "pytubefix",
            "ts": now - age,
            "ttl": ttl,
        }

    def test_returns_cached_entry_when_valid(self):
        from services import audio_service
        entry = self._make_entry("vid1")
        audio_service._cache["vid1"] = entry

        with patch("services.audio_service._extract_best_url") as mock_extract:
            result = _get_or_extract("vid1")

        assert result == entry
        mock_extract.assert_not_called()

    def test_extracts_when_cache_miss(self):
        info = {"title": "Creep"}
        url = "https://audio.example.com/new"
        with patch("services.audio_service._extract_best_url", return_value=(info, url, "pytubefix")):
            result = _get_or_extract("vid_new")

        assert result["direct_url"] == url
        assert result["client"] == "pytubefix"

    def test_extracts_when_cache_expired(self):
        from services import audio_service
        expired = self._make_entry("vid1", age=URL_TTL + 100)
        audio_service._cache["vid1"] = expired

        info = {"title": "Fresh"}
        url = "https://audio.example.com/fresh"
        with patch("services.audio_service._extract_best_url", return_value=(info, url, "yt-dlp")):
            result = _get_or_extract("vid1")

        assert result["direct_url"] == url

    def test_force_bypasses_valid_cache(self):
        from services import audio_service
        entry = self._make_entry("vid1")
        audio_service._cache["vid1"] = entry

        info = {"title": "Forced"}
        url = "https://audio.example.com/forced"
        with patch("services.audio_service._extract_best_url", return_value=(info, url, "pytubefix")):
            result = _get_or_extract("vid1", _force=True)

        assert result["direct_url"] == url

    def test_stores_new_entry_in_cache(self):
        from services import audio_service
        url = "https://audio.example.com/stored"
        with patch("services.audio_service._extract_best_url", return_value=({}, url, "pytubefix")):
            _get_or_extract("vid_store")

        assert "vid_store" in audio_service._cache
        assert audio_service._cache["vid_store"]["direct_url"] == url