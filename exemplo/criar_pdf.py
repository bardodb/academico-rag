from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent
PDF = ROOT / "compostagem.pdf"
FONT = r"C:\Windows\Fonts\times.ttf"


def main() -> None:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_font(fontname="times", fontfile=FONT)
    page.insert_text((72, 72), "Costa, Helena. 2021.", fontname="times", fontsize=12)
    page.insert_text((72, 110), "Compostagem urbana", fontname="times", fontsize=18)
    page.insert_textbox(
        pymupdf.Rect(72, 140, 540, 780),
        (
            "A compostagem urbana transforma restos de alimentos em adubo. "
            "O processo aeróbio eleva a temperatura da leira acima de 55 graus Celsius "
            "por pelo menos três dias, o que reduz patógenos. "
            "A proporção recomendada é de três partes de material seco para uma parte de material úmido."
        ),
        fontname="times",
        fontsize=12,
    )
    second = document.new_page()
    second.insert_font(fontname="times", fontfile=FONT)
    second.insert_text((72, 72), "Umidade e chorume", fontname="times", fontsize=16)
    second.insert_textbox(
        pymupdf.Rect(72, 110, 540, 780),
        (
            "A umidade adequada fica entre 50 e 60 por cento. "
            "O chorume deve ser reaplicado sobre a leira e não descartado em rede pluvial."
        ),
        fontname="times",
        fontsize=12,
    )
    document.save(PDF)
    document.close()
    print(PDF)


if __name__ == "__main__":
    main()
