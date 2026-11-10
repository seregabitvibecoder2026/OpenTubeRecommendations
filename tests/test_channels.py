import pytest

from app import collect
from app.providers import watchpage


@pytest.mark.parametrize("inp,exp", [
    ("UCsXVk37bltHxD1rDPwtNM8Q", ("id", "UCsXVk37bltHxD1rDPwtNM8Q")),
    ("https://www.youtube.com/channel/UCsXVk37bltHxD1rDPwtNM8Q/videos", ("id", "UCsXVk37bltHxD1rDPwtNM8Q")),
    ("@kurzgesagt", ("url", "https://www.youtube.com/@kurzgesagt")),
    ("https://youtube.com/@vdud/featured", ("url", "https://www.youtube.com/@vdud")),
    ("youtube.com/c/Name", ("url", "https://www.youtube.com/c/Name")),
    ("https://www.youtube.com/watch?v=5_Fayfx2NUM&t=10", ("video", "5_Fayfx2NUM")),
    ("https://youtu.be/5_Fayfx2NUM?si=x", ("video", "5_Fayfx2NUM")),
    ("https://www.youtube.com/shorts/5_Fayfx2NUM", ("video", "5_Fayfx2NUM")),
    ("kurzgesagt", ("url", "https://www.youtube.com/@kurzgesagt")),
])
def test_parse_channel_input(inp, exp):
    assert watchpage.parse_channel_input(inp) == exp


def test_takeout_csv_any_language():
    ru = "Идентификатор канала,URL канала,Название канала\nUCsXVk37bltHxD1rDPwtNM8Q,http://www.youtube.com/channel/UCsXVk37bltHxD1rDPwtNM8Q,Kurzgesagt\n\n"
    en = "﻿Channel Id,Channel Url,Channel Title\nUCMCgOm8GZkHp8zJ6l7_hIuA,http://www.youtube.com/channel/UCMCgOm8GZkHp8zJ6l7_hIuA,вДудь\n"
    assert collect.parse_takeout_csv(ru) == [{"id": "UCsXVk37bltHxD1rDPwtNM8Q", "title": "Kurzgesagt"}]
    assert collect.parse_takeout_csv(en) == [{"id": "UCMCgOm8GZkHp8zJ6l7_hIuA", "title": "вДудь"}]


def test_split_inputs():
    assert collect.split_inputs("@a, @b;\nhttps://x  ") == ["@a", "@b", "https://x"]


def test_watchpage_parses_age_restricted_html(monkeypatch):
    html = ('<script>var ytInitialPlayerResponse = {"playabilityStatus":{"status":"LOGIN_REQUIRED","reason":"Sign in to confirm your age"},'
            '"videoDetails":{"videoId":"07FYdnEawAQ","title":"T","lengthSeconds":"419","keywords":["a"],"channelId":"UCsXfDf1CDgU3SCt0gxJNXGg",'
            '"shortDescription":"desc","viewCount":"18"},"microformat":{"playerMicroformatRenderer":{"publishDate":"2013-07-03T15:00:16-07:00",'
            '"isFamilySafe":false}}};var meta = 1;</script>')

    class R:
        status_code = 200
        text = html
    monkeypatch.setattr("app.net.get", lambda *a, **k: R())
    m = watchpage.video_meta("07FYdnEawAQ")
    assert m["age_restricted"] == 1 and m["duration"] == 419 and m["tags"] == ["a"] and m["description"] == "desc"
    assert m["published_at"] and m["channel_id"] == "UCsXfDf1CDgU3SCt0gxJNXGg"
