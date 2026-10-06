from processing.location import extract_location


def test_full_address_gives_most_specific_query_first():
    loc = extract_location(
        "İzmit’te iki aracın karıştığı kaza trafiği etkiledi",
        "Kocaeli’nin İzmit ilçesi Yenişehir Mahallesi Paşa Caddesi Dönmez Sokak’ta iki aracın "
        "karıştığı maddi hasarlı trafik kazası meydana geldi.",
    )
    texts = [c.text for c in loc.candidates]
    assert loc.district == "İzmit"
    assert {"Yenişehir Mahallesi", "Paşa Caddesi", "Dönmez Sokak"} <= set(texts)
    assert loc.queries[0].query == "Dönmez Sokak, Paşa Caddesi, Yenişehir Mahallesi, İzmit, Kocaeli"
    assert loc.queries[-1].query == "İzmit, Kocaeli"


def test_other_province_news_is_not_local():
    loc = extract_location(
        "Bursa'da orman yangını",
        "Bursa'nın Kestel ilçesinde ormanda yangın çıktı. Kestel ilçesi Gölcük Mahallesi'ndeki "
        "tarım arazisinde çıkan yangın ormana sıçradı.",
    )
    assert loc.is_local is False
    assert loc.district is None      # "Gölcük Mahallesi" ilçe sayılmadı


def test_direction_phrases_do_not_count_as_location():
    loc = extract_location(
        "Kocaeli istikametine gelen araç takla attı",
        "Yalova'nın Çiftlikköy ilçesinde, Kocaeli istikametine giden otomobil takla attı. "
        "Kaza Çiftlikköy ilçesi Yalova-İzmit kara yolu üzerinde gerçekleşti.",
    )
    assert loc.is_local is False


def test_border_news_with_kocaeli_district_is_local_and_ignores_foreign_neighbourhoods():
    loc = extract_location(
        "Karamürsel-İznik sınırında orman yangını",
        "Kocaeli’nin Karamürsel ilçesi ile Bursa’nın İznik ilçesi sınırında yangın çıktı. "
        "Yangın Karamürsel’in Fulacık ve Tahtalı mahalleleri ile İznik’in Sarıalan ve Yörükler "
        "mahallelerinin bulunduğu bölgede çıktı.",
    )
    texts = [c.text for c in loc.candidates]
    assert loc.is_local and loc.district == "Karamürsel"
    assert "Fulacık Mahallesi" in texts and "Sarıalan Mahallesi" not in texts


def test_poi_road_and_hospital_exclusion():
    loc = extract_location(
        "D-100’de çarpışma",
        "Kocaeli’nin Kartepe ilçesinde D-100 kara yolu Askeriye Sapağı mevkiinde otomobil "
        "kamyonete çarptı. Yaralı Kocaeli Şehir Hastanesi'ne kaldırıldı.",
    )
    texts = [c.text for c in loc.candidates]
    assert "Askeriye Sapağı" in texts and "D-100 Karayolu" in texts
    assert not any("Hastane" in t for t in texts)
    assert loc.queries[0].query == "Askeriye Sapağı, Kartepe, Kocaeli"


def test_sentence_start_words_are_not_part_of_names():
    loc = extract_location("Yangın", "Olay Kısalar Mahallesi'nde yaşandı. İzmit'in Karabaş Mahallesi'nde de duman görüldü.")
    texts = [c.text for c in loc.candidates]
    assert "Kısalar Mahallesi" in texts and "Karabaş Mahallesi" in texts


def test_known_place_without_district():
    loc = extract_location("Sekapark'ta konser", "Büyükşehir Belediyesi Sekapark'ta açık hava konseri düzenleyecek.")
    assert loc.queries and loc.queries[0].query == "Sekapark, Kocaeli"


def test_no_location_found():
    loc = extract_location("Hırsızlar yakalandı", "Polis ekipleri hırsızlık şüphelilerini yakaladı.")
    assert loc.found is False
