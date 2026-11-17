"""Tests for configurable preview-only video parsing (no live network)."""

import asyncio

import pytest


@pytest.mark.parametrize(
    ("global_enabled", "overrides", "platform", "expected"),
    [
        (True, {}, "bilibili", True),
        (True, {"bilibili": False}, "bilibili", False),
        (True, {"bilibili": False}, "douyin", True),
        (True, {"bilibili": True, "douyin": False}, "bilibili", True),
        (True, {"bilibili": True, "douyin": False}, "douyin", False),
        (False, {}, "bilibili", False),
        (False, {"bilibili": True}, "bilibili", False),
    ],
)
def test_per_platform_configuration(global_enabled, overrides, platform, expected):
    from nonebot_plugin_parser.config import Config

    config = Config(
        parser_download_video=global_enabled,
        parser_download_video_platforms=overrides,
    )
    assert config.is_video_download_enabled(platform) is expected


@pytest.mark.asyncio
async def test_one_platform_disabled_other_enabled(monkeypatch, tmp_path):
    from nonebot_plugin_parser.config import pconfig
    from nonebot_plugin_parser.constants import PlatformEnum
    from nonebot_plugin_parser.download import downloader
    from nonebot_plugin_parser.parsers.base import BaseParser
    from nonebot_plugin_parser.parsers.data import ParseResult, Platform
    from nonebot_plugin_parser.renders.default import DefaultRenderer

    class BiliParser(BaseParser):
        platform = Platform(name=PlatformEnum.BILIBILI, display_name="Bili")

    class DouyinParser(BaseParser):
        platform = Platform(name=PlatformEnum.DOUYIN, display_name="Douyin")

    monkeypatch.setattr(pconfig, "parser_download_video", True)
    monkeypatch.setattr(pconfig, "parser_download_video_platforms", {"bilibili": False, "douyin": True})

    calls = []
    cover_path = tmp_path / "cover.jpg"
    video_path = tmp_path / "video.mp4"

    def fake_video(*args, **kwargs):
        calls.append("video")
        async def work():
            return video_path
        return asyncio.create_task(work())

    def fake_cover(*args, **kwargs):
        calls.append("cover")
        async def work():
            return cover_path
        return asyncio.create_task(work())

    monkeypatch.setattr(downloader, "download_video", fake_video)
    monkeypatch.setattr(downloader, "download_img", fake_cover)

    disabled = BiliParser().create_video(
        "https://example.com/video.mp4",
        cover_url="https://example.com/cover.jpg",
        duration=120,
    )
    assert disabled.path_task.disabled
    assert not disabled.gif_path
    assert calls == ["cover"]
    assert disabled.duration == 120
    assert await disabled.cover.get() == cover_path

    bili_result = ParseResult(platform=BiliParser.platform, contents=[disabled])
    assert bili_result.video is disabled
    await bili_result.ensure_downloads_complete(suppress_errors=False)
    assert [message async for message in DefaultRenderer(bili_result).render_contents()] == []

    enabled = DouyinParser().create_video(
        "https://example.com/video.mp4",
        cover_url="https://example.com/cover.jpg",
    )
    assert not enabled.path_task.disabled
    assert await enabled.path_task.get() == video_path
    assert await enabled.cover.get() == cover_path
    assert calls == ["cover", "video", "cover"]


@pytest.mark.asyncio
async def test_disabled_platform_does_not_call_lazy_factory(monkeypatch):
    from nonebot_plugin_parser.config import pconfig
    from nonebot_plugin_parser.constants import PlatformEnum
    from nonebot_plugin_parser.parsers.base import BaseParser
    from nonebot_plugin_parser.parsers.data import Platform

    class BiliParser(BaseParser):
        platform = Platform(name=PlatformEnum.BILIBILI, display_name="Bili")

    monkeypatch.setattr(pconfig, "parser_download_video", True)
    monkeypatch.setattr(pconfig, "parser_download_video_platforms", {"bilibili": False})

    def fail_factory():
        raise AssertionError("Video download must not be started")

    video = BiliParser().create_video(fail_factory, cover_url=None)
    assert video.path_task.disabled
    assert video.cover is None
    assert await video.path_task.safe_get() is None


@pytest.mark.asyncio
async def test_global_switch_takes_precedence(monkeypatch):
    from nonebot_plugin_parser.config import pconfig
    from nonebot_plugin_parser.constants import PlatformEnum
    from nonebot_plugin_parser.parsers.base import BaseParser
    from nonebot_plugin_parser.parsers.data import Platform

    class BiliParser(BaseParser):
        platform = Platform(name=PlatformEnum.BILIBILI, display_name="Bili")

    monkeypatch.setattr(pconfig, "parser_download_video", False)
    monkeypatch.setattr(pconfig, "parser_download_video_platforms", {"bilibili": True})

    video = BiliParser().create_video(lambda: (_ for _ in ()).throw(AssertionError("downloaded")))
    assert video.path_task.disabled
    assert video.cover is None


@pytest.mark.asyncio
async def test_direct_stream_downloads_rejected_when_globally_disabled(monkeypatch):
    from nonebot_plugin_parser.config import pconfig
    from nonebot_plugin_parser.download import downloader
    from nonebot_plugin_parser.exception import IgnoreException

    monkeypatch.setattr(pconfig, "parser_download_video", False)
    with pytest.raises(IgnoreException):
        await downloader.download_video("https://example.com/video.mp4")
    with pytest.raises(IgnoreException):
        await downloader.download_m3u8("https://example.com/video.m3u8")
    with pytest.raises(IgnoreException):
        await downloader.download_av_and_merge(
            "https://a", "https://b", output_path=pconfig.cache_dir / "test.mp4"
        )


@pytest.mark.parametrize("enabled", [False, True])
def test_ytdlp_progress_options(monkeypatch, enabled):
    pytest.importorskip("yt_dlp")
    from nonebot_plugin_parser.config import pconfig
    from nonebot_plugin_parser.download.ytdlp import YtdlpDownloader

    monkeypatch.setattr(pconfig, "parser_show_download_progress", enabled)
    downloader = YtdlpDownloader()
    assert downloader._download_base_opts["quiet"] is not enabled
    assert downloader._download_base_opts["noprogress"] is not enabled
