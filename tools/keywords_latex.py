"""
Raporda listelenmesi zorunlu olan anahtar kelimeleri LaTeX tablosu olarak üretir.
Kelimeler doğrudan processing/classifier.py'den okunur; kod değişirse tablo da
güncel kalır.

Kullanım (proje klasöründe):
    python -m tools.keywords_latex > anahtar_kelimeler.tex
Raporda:
    \\input{anahtar_kelimeler.tex}
(booktabs paketi gerekir; tablo IEEEtran'ın iki sütunlu düzenine uygundur.)
"""
from __future__ import annotations

from processing.classifier import ANCHOR_WEIGHT, CLOSE_RATIO, KEYWORDS, MIN_SCORE, PRIORITY, TITLE_WEIGHT

_LATEX_ESCAPES = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
    "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\^{}",
}


def esc(text: str) -> str:
    return "".join(_LATEX_ESCAPES.get(ch, ch) for ch in text)


def keyword_label(keyword: str) -> str:
    # Kelimelerin çoğu kök olarak eşleşir ("yangın" -> "yangında"); yalnızca tam
    # biçimle eşleşenler ("kaza$" -> "kaza" evet, "kazanç" hayır) işaretlenir.
    if keyword.endswith("$"):
        return esc(keyword[:-1]) + r"\textsuperscript{\dag}"
    return esc(keyword)


def build() -> str:
    """IEEEtran (iki sütunlu) düzenine uygun, sayfa genişliğinde bir tablo üretir."""
    lines = [
        r"\begin{table*}[!t]",
        # IEEEtran tablo başlıklarını büyük harfe çevirir ve Türkçe i -> I yapar;
        # bu yüzden başlık doğrudan büyük harfle (İ ile) yazılır.
        r"\caption{SINIFLANDIRMADA KULLANILAN ANAHTAR KELİMELER VE AĞIRLIKLARI}",
        r"\label{tab:anahtar}",
        r"\centering\footnotesize",
        r"\begin{tabular}{@{}p{0.15\textwidth}p{0.05\textwidth}p{0.74\textwidth}@{}}",
        r"\toprule",
        r"\textbf{Haber türü} & \textbf{Ağırlık} & \textbf{Anahtar kelimeler} \\",
        r"\midrule",
    ]
    for category in PRIORITY:
        by_weight: dict[int, list[str]] = {}
        for kw, weight in KEYWORDS[category]:
            by_weight.setdefault(weight, []).append(keyword_label(kw))
        first = True
        for weight in sorted(by_weight, reverse=True):
            name = esc(category) if first else ""
            lines.append(f"{name} & {weight:+d} & {', '.join(by_weight[weight])} \\\\")
            first = False
        lines.append(r"\midrule")
    lines[-1] = r"\bottomrule"
    lines.append(r"\end{tabular}")
    lines.append(r"\par\vspace{3pt}\begin{minipage}{0.96\textwidth}\footnotesize")
    lines.append(
        r"Kelimeler kök olarak eşleşir; Türkçe ekleriyle birlikte de bulunur "
        r"(ör. \emph{yangın} $\rightarrow$ \emph{yangında}). "
        r"\textsuperscript{\dag}~ile işaretli kelimeler yalnızca tam kelime olarak eşleşir "
        r"(ör. \emph{kaza} eşleşir, \emph{kazanç} eşleşmez). Negatif ağırlıklar yanlış "
        r"eşleşmeleri bastırır. "
        rf"Başlıktaki eşleşmeler {TITLE_WEIGHT} kat sayılır. Bir türün seçilebilmesi için haberde o "
        rf"türün ağırlığı en az {ANCHOR_WEIGHT} olan bir kelimesi geçmeli ve toplam puanı en az "
        rf"{MIN_SCORE} olmalıdır. Puanı en yüksek puanın en az \%{int(CLOSE_RATIO * 100)}'ı olan "
        r"türler arasından öncelik sırasına göre seçim yapılır: "
        + r" $>$ ".join(esc(c) for c in PRIORITY) + "."
    )
    lines.append(r"\end{minipage}")
    lines.append(r"\end{table*}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(build())
