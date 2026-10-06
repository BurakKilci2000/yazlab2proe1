import pytest

from processing.classifier import CATEGORIES, KEYWORDS, PRIORITY, classify


@pytest.mark.parametrize("title,content,expected", [
    ("İzmit'te zincirleme kaza", "D-100 karayolunda 3 otomobil çarpıştı, araçlarda maddi hasar oluştu.", "Trafik Kazası"),
    ("Market küle döndü", "İzmit'te markette çıkan yangın itfaiye ekiplerince söndürüldü.", "Yangın"),
    ("Gebze'de planlı kesinti", "SEDAŞ yarın 09.00-15.00 arasında elektrik verilemeyeceğini duyurdu.", "Elektrik Kesintisi"),
    ("Evden altın çaldılar", "Hırsızlar evden ziynet eşyalarını çalarak kaçtı, şüpheliler yakalandı.", "Hırsızlık"),
    ("Sekapark'ta yaz konseri", "Büyükşehir Belediyesi'nin düzenlediği konserde sanatçılar sahne aldı.", "Kültürel Etkinlikler"),
])
def test_categories(title, content, expected):
    assert classify(title, content).category == expected


def test_unrelated_news_has_no_category():
    assert classify("Belediye meclisi toplandı", "Meclis üyeleri bütçe görüşmelerini tamamladı.").category is None


def test_negative_keywords():
    assert classify("Su kesintisi duyurusu", "İSU yarın su kesintisi yapılacağını duyurdu.").category is None
    assert classify("Okulda yangın tatbikatı", "Öğrenciler yangın tatbikatına katıldı.").category is None
    assert classify("Fabrikada iş kazası", "İş kazasında işçi yaralandı.").category != "Trafik Kazası"


def test_exact_word_keyword_does_not_match_longer_word():
    # "kaza$" tam kelime: "kazandı" eşleşmemeli
    assert classify("Kocaelispor kazandı", "Takım deplasmanda 2-0 kazandı ve puanını artırdı.").category is None


def test_priority_when_two_categories_are_strong():
    result = classify(
        "Zincirleme kazada araç alev aldı",
        "D-100'de üç otomobil çarpıştı. Zincirleme trafik kazasında araçlardan biri alev aldı, "
        "yangın kısa sürede söndürüldü.",
    )
    # Trafik puanı daha yüksek olsa da iki tür de güçlü aday -> öncelik sırası Yangın'ı seçer
    assert {"Trafik Kazası", "Yangın"} <= set(result.candidates)
    assert result.category == "Yangın"           # öncelik sırası


def test_keyword_table_is_consistent():
    assert set(KEYWORDS) == set(CATEGORIES) == set(PRIORITY)


@pytest.mark.parametrize("title,content", [
    ("Kocaeli'de uyuşturucu operasyonu!", "Operasyonda şüpheliler gözaltına alındı, uyuşturucu ele geçirildi, şüpheliler tutuklandı."),
    ("Kardeşini öldürdü", "Gebze'de kardeşini öldüren şüpheli yakalandı ve tutuklandı."),
    ("Genç yetenek Fenerbahçe'de", "Gölcük'te futbola başlayan oyuncu Fenerbahçe'ye transfer oldu, sahneye çıktığı her maçta parladı."),
    ("Darıca'ya yeni kavşak", "Trafik kazalarının sık yaşandığı noktaya yeni kavşak yapılacak, ihale tamamlandı."),
    ("KSO'da yeni meclis belli oldu", "Kocaeli Sanayi Odası seçimlerinde elektrik ve enerji firmaları ile SEDAŞ yarıştı."),
])
def test_real_world_false_positives_are_rejected(title, content):
    # Gerçek taramada yanlış sınıflanan haberlerden türetilen örnekler
    assert classify(title, content).category is None


def test_weak_keywords_alone_are_not_enough():
    # "şüpheli + yakalandı + tutuklandı + gözaltına" zayıf kelimeler: toplamı eşiği geçse de yetmez
    result = classify("Şüpheliler yakalandı", "Şüpheli gözaltına alındı. Şüpheli tutuklandı. Şüpheli yakalandı.")
    assert result.scores["Hırsızlık"] >= 4 and result.category is None


def test_consonant_softening_in_power_outage():
    assert classify("Duyuru", "Yarın bazı mahallelere elektrik verilemeyeceği bildirildi.").category == "Elektrik Kesintisi"


@pytest.mark.parametrize("word,text", [
    ("opera", "Narkotik ekipleri operasyon düzenledi."),          # opera ⊄ operasyon
    ("sergi", "Takım sahada iyi bir performans sergiledi."),      # sergi ⊄ sergiledi
    ("konser", "Fabrikada konserve üretimi arttı."),             # konser ⊄ konserve
])
def test_stem_matching_traps(word, text):
    # Gerçek taramada görülen kök eşleşme tuzakları: kültürel kelime sayılmamalı
    assert word not in classify("Haber", text).matched.get("Kültürel Etkinlikler", [])


def test_real_culture_words_still_match():
    for text in ("Opera sanatçıları sahne aldı.", "Resim sergisi açıldı.", "Sekapark'ta konserde buluştular."):
        assert classify("Etkinlik", text).category == "Kültürel Etkinlikler", text


def test_overturned_motorcycle_is_traffic_accident_but_fallen_tree_is_not():
    # Gerçek taramada güçlü kelime şartı yüzünden kaçırılan kaza haberi
    assert classify("Devrilen motosikletin sürücüsü yaralandı",
                    "Dilovası'nda motosiklet devrildi, 41 ABC 123 plakalı motosikletin sürücüsü yaralandı."
                    ).category == "Trafik Kazası"
    assert classify("Fırtına", "Şiddetli rüzgarda ağaç devrildi, park halindeki araç hasar gördü.").category is None


def test_calindi_alone_is_not_theft():
    # Gerçek taramada: mağdurların "emeğimiz çalındı" sözü haberi Hırsızlık yapıyordu
    assert classify("Mağdurları dinledi", "Mağdurlar bir yıldır emeklerinin çalındığını anlattı.").category is None
    assert classify("Tören", "Törende İstiklal Marşı çalındı.").category is None
    # Gerçek hırsızlık haberleri hâlâ yakalanmalı
    assert classify("Evden ziynet eşyası çalındı", "Gebze'de bir evden altınlar çalındı.").category == "Hırsızlık"
    assert classify("Gebze'de olay", "Evden altınlar çalındı, polis şüpheliyi arıyor.").category == "Hırsızlık"
