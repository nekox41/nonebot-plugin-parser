"""媒体下载开关的离线回归测试。"""

import asyncio

import pytest


@pytest.mark.asyncio
async def test_video_disabled_preserves_cover_without_starting_download(monkeypatch, tmp_path):
    from nonebot_plugin_parser.config import pconfig
    from nonebot_plugin_parser.download import downloader
    from nonebot_plugin_parser.parsers.base import BaseParser
    from nonebot_plugin_parser.parsers.data import ParseResult, Platform
    from nonebot_plugin_parser.renders.default import DefaultRenderer

    monkeypatch.setattr(pconfig, "parser_download_video", False)
    cover_path = tmp_path / "cover.jpg"

    def fail_video_download(*args, **kwargs):
        raise AssertionError("video download must not be started")

    async def fake_cover():
        return cover_path

    def fake_download_img(*args, **kwargs):
        return asyncio.create_task(fake_cover())

    monkeypatch.setattr(downloader, "download_video", fail_video_download)
    monkeypatch.setattr(downloader, "download_img", fake_download_img)

    parser = BaseParser()
    video = parser.create_video(
        "https://example.com/video.mp4",
        cover_url="https://example.com/cover.jpg",
        duration=120,
    )
    assert video.duration == 120
    assert video.cover is not None
    assert await video.cover.get() == cover_path
    assert await video.path_task.safe_get() is None

    result = ParseResult(platform=Platform(name="test", display_name="Test"), contents=[video])
    assert result.video is video
    await result.ensure_downloads_complete()
    assert [message async for message in DefaultRenderer(result).render_contents()] == []


@pytest.mark.asyncio
async def test_disabled_video_does_not_call_lazy_factory(monkeypatch):
    from nonebot_plugin_parser.config import pconfig
    from nonebot_plugin_parser.parsers.base import BaseParser

    monkeypatch.setattr(pconfig, "parser_download_video", False)

    def fail_factory():
        raise AssertionError("video download factory must not be invoked")

    video = BaseParser().create_video(fail_factory, cover_url=None)
    assert await video.path_task.safe_get() is None
    assert video.cover is None


@pytest.mark.asyncio
async def test_enabled_video_starts_lazy_download(monkeypatch, tmp_path):
    from nonebot_plugin_parser.config import pconfig
    from nonebot_plugin_parser.download import downloader
    from nonebot_plugin_parser.parsers.base import BaseParser

    monkeypatch.setattr(pconfig, "parser_download_video", True)
    video_path = tmp_path / "video.mp4"
    cover_path = tmp_path / "cover.jpg"
    calls = []

    async def fake_download():
        calls.append("download")
        return video_path

    async def fake_cover():
        return cover_path

    monkeypatch.setattr(downloader, "download_img", lambda *a, **k: asyncio.create_task(fake_cover()))
    video = BaseParser().create_video(
        lambda: asyncio.create_task(fake_download()),
        cover_url="https://example.com/cover.jpg",
    )
    assert await video.path_task.get() == video_path
    assert video.cover is not None
    assert await video.cover.get() == cover_path
    assert calls == ["download"]


@pytest.mark.asyncio
async def test_stream_video_download_rejected_when_disabled(monkeypatch):
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
