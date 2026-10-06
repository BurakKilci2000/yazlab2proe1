from processing.cleaner import build_article_text, clean_html, clean_text, remove_special_characters
from utils.text import ascii_fold, normalize_for_matching, turkish_lower


def test_turkish_lower_handles_dotted_and_dotless_i():
    assert turkish_lower("İZMİT IŞIK") == "izmit ışık"
    assert "İZMİT".lower() != "izmit"          # Python'un kendi lower()'ı yanlış


def test_normalize_for_matching():
    assert normalize_for_matching("Direksiyon HÂKİMİYETİNİ kaybetti!") == "direksiyon hakimiyetini kaybetti"
    assert normalize_for_matching("Kocaeli’nin  İzmit’te") == "kocaelinin izmitte"


def test_ascii_fold():
    assert ascii_fold("İzmit") == ascii_fold("Izmit") == "izmit"


def test_remove_special_characters_drops_emoji_and_repeated_punctuation():
    assert remove_special_characters("Kaza oldu!!! 🚗💥 ₺100 %5").split() == ["Kaza", "oldu!", "₺100", "%5"]


def test_clean_html_removes_ads_related_captions_and_noise(fixture_html):
    html = fixture_html("cms_article.html")
    text = clean_html(html, "Kaza yapan otomobil sürücüsü baygınlık geçirdi!")
    assert "Fatih Mahallesi Akşemsettin Caddesi'nde" in text
    assert "REKLAM" not in text
    assert "İlgili Haber" not in text
    assert "ABONE OL" not in text
    assert "Topluluk Kuralları" not in text
    assert "<" not in text and "🚗" not in text
    assert "  " not in text                      # fazla boşluk yok
    assert "Kaza yapan otomobil sürücüsü baygınlık geçirdi!" not in text  # tekrarlanan başlık


def test_clean_text_unescapes_and_splits():
    text = clean_text("Kaza &amp; yangın aynı gün yaşandı.\n\nİkinci paragraf burada yer alıyor.")
    assert text == "Kaza & yangın aynı gün yaşandı.\nİkinci paragraf burada yer alıyor."


def test_build_article_text_prepends_spot_when_missing():
    text = build_article_text(
        "Başlık", "<p>Kaza sonrası sürücü hastaneye kaldırıldı ve tedavi altına alındı.</p>",
        "", "Kocaeli'nin Kartepe ilçesi İbrikdere Mahallesi'nde maddi hasarlı kaza meydana geldi.",
    )
    assert text.startswith("Kocaeli'nin Kartepe ilçesi İbrikdere")
