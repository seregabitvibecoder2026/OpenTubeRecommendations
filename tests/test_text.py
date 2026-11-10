from app import config, text


def test_detect_lang_ru_en():
    assert text.detect_lang("Как делают кино: бездомные, миллионы и Киану Ривз") == "ru"
    assert text.detect_lang("How I Survived Late-Stage Cancer (A Fun Story)") == "en"
    assert text.detect_lang("We finally know more about humanity's first civilization") == "en"
    assert text.detect_lang("ШКЯ – легенда русского интернета") == "ru"
    assert text.detect_lang("anything", hint="en-US") == "en"
    assert text.detect_lang("") is None
    assert text.detect_lang("12345 !!!") is None


def test_profanity_ru():
    pats = config.PROFANITY_RU
    d, n, w = text.profanity_density("Бля, ну это пиздец, нахуй такое. Сука, заебал!", pats)
    assert n == 5 and w == 8
    # no false positives on innocent words
    _, n2, _ = text.profanity_density("хлеб мандарин употреблять небеса оскорблять скипидар сукно", pats)
    assert n2 == 0


def test_profanity_en():
    pats = config.PROFANITY_EN
    _, n, _ = text.profanity_density("What the fuck, this is bullshit. Motherfucker! Fucking great", pats)
    assert n == 4
    _, n2, _ = text.profanity_density("assessment of a classic shipment, Scunthorpe and passion", pats)
    assert n2 == 0


def test_phrase_and_glob_rules():
    tl = "смешные коты и #shorts про политику"
    toks = set(text.tokens(tl))
    assert text.phrase_in(tl, toks, "#shorts")
    assert text.phrase_in(tl, toks, "полит*")
    assert text.phrase_in(tl, toks, "смешные коты")
    assert not text.phrase_in(tl, toks, "кот")  # whole tokens only, use кот* for prefixes
    assert text.phrase_in(tl, toks, "кот*")


def test_clean_comments_filters_spam():
    cs = [{"text": "12:34", "like_count": 900}, {"text": "Discover X 👉 https://spam.example/r", "like_count": 800},
          {"text": "Это лучший выпуск, ржал весь вечер", "like_count": 500},
          {"text": "Это лучший выпуск, ржал весь вечер!", "like_count": 100},
          {"text": "😂😂😂😂😂😂😂😂😂😂", "like_count": 50}, {"text": "Great video, the cat part was hilarious", "like_count": 10}]
    out = text.clean_comments(cs).splitlines()
    assert out == ["Это лучший выпуск, ржал весь вечер", "Great video, the cat part was hilarious"]
