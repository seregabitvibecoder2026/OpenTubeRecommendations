import pytest

from app.providers import rss

SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">
 <title>Test Channel</title>
 <yt:channelId>UCsXVk37bltHxD1rDPwtNM8Q</yt:channelId>
 <entry>
  <id>yt:video:5_Fayfx2NUM</id>
  <yt:videoId>5_Fayfx2NUM</yt:videoId>
  <yt:channelId>UCsXVk37bltHxD1rDPwtNM8Q</yt:channelId>
  <title>How I Survived</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=5_Fayfx2NUM"/>
  <published>2026-10-27T15:00:01+00:00</published>
  <media:group><media:title>How I Survived</media:title><media:description>desc text</media:description>
   <media:community><media:statistics views="8300000"/></media:community></media:group>
 </entry>
 <entry>
  <yt:videoId>AAAAAAAAAAA</yt:videoId>
  <title>A short</title>
  <link rel="alternate" href="https://www.youtube.com/shorts/AAAAAAAAAAA"/>
  <published>2026-10-28T10:00:00+00:00</published>
 </entry>
</feed>"""


def test_parse_rss():
    d = rss.parse(SAMPLE)
    assert d["channel_id"] == "UCsXVk37bltHxD1rDPwtNM8Q"
    assert d["channel_title"] == "Test Channel"
    e = d["entries"]
    assert [x["id"] for x in e] == ["5_Fayfx2NUM", "AAAAAAAAAAA"]
    assert e[0]["views"] == 8300000 and e[0]["description"] == "desc text"
    assert e[0]["published_at"] == pytest.approx(1793113201, abs=1)
    assert e[0]["is_short"] == 0 and e[1]["is_short"] == 1


def test_parse_broken_rss():
    from app.providers import ProviderError
    with pytest.raises(ProviderError):
        rss.parse("<html>404</html")


def test_long_playlist_ids():
    assert rss.long_playlist_id("UCsXVk37bltHxD1rDPwtNM8Q") == "UULFsXVk37bltHxD1rDPwtNM8Q"
    assert rss.shorts_playlist_id("UCsXVk37bltHxD1rDPwtNM8Q") == "UUSHsXVk37bltHxD1rDPwtNM8Q"
    with pytest.raises(ValueError):
        rss.long_playlist_id("PLxxxx")


def test_listing_shorts_flag_filtered(monkeypatch):
    """RSS entries with /shorts/ links never reach the feed."""
    from app import collect, ranking
    from tests.helpers import new_profile
    pid = new_profile(exploration=0, min_duration_sec=0)
    cid = "UCsXVk37bltHxD1rDPwtNM8Q"
    collect.upsert_channel(cid, "T")
    collect.attach(pid, cid)
    collect.upsert_listing(rss.parse(SAMPLE)["entries"], cid)
    ids = [it["v"]["id"] for it in ranking.compute(pid)["items"]]
    assert ids == ["5_Fayfx2NUM"]


def test_json3_and_vtt_text():
    from app.providers import altfront, ytdlp
    d = {"events": [{"segs": [{"utf8": "привет "}, {"utf8": "мир"}]}, {"tStartMs": 1}, {"segs": [{"utf8": "[Музыка]"}]},
                    {"segs": [{"utf8": "hello\nworld"}]}]}
    assert ytdlp.json3_to_text(d) == "привет мир hello world"
    vtt = "WEBVTT\nKind: captions\n\n00:00.000 --> 00:01.000\n<c>one</c> two\n\n00:01.000 --> 00:02.000\none two\nthree\n"
    assert altfront.vtt_to_text(vtt) == "one two three"


def test_pick_sub_track_prefers_manual_then_orig():
    from app.providers import ytdlp
    j = lambda u: [{"ext": "vtt", "url": "x"}, {"ext": "json3", "url": u}]  # noqa: E731
    info = {"language": "ru", "subtitles": {}, "automatic_captions": {"ru-orig": j("auto-ru"), "en": j("auto-en")}}
    assert ytdlp.pick_sub_track(info, ["ru", "en"]) == ("ru", "auto-ru", True)
    info["subtitles"] = {"en": j("man-en")}
    assert ytdlp.pick_sub_track(info, ["ru", "en"]) == ("en", "man-en", False)
    assert ytdlp.pick_sub_track({"subtitles": {}, "automatic_captions": {}}, ["ru"]) is None
