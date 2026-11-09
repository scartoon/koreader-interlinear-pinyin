#!/usr/bin/env python3
"""Build samples/guwen.epub: three short classical Chinese texts, all in the
public domain, used for the README screenshots and for trying the plugin.

    python3 tools/make_sample_epub.py

  桃花源记  陶渊明 (365–427)
  陋室铭    刘禹锡 (772–842)
  爱莲说    周敦颐 (1017–1073)

The style sheet deliberately sets no line-height, like most books, so the
screenshots show the plugin's real effect on line spacing.
"""
import os
import zipfile

TEXTS = [
    ("桃花源记", "陶渊明", [
        "晋太元中，武陵人捕鱼为业。缘溪行，忘路之远近。忽逢桃花林，夹岸数百步，中无杂树，芳草鲜美，落英缤纷。渔人甚异之，复前行，欲穷其林。",
        "林尽水源，便得一山，山有小口，仿佛若有光。便舍船，从口入。初极狭，才通人。复行数十步，豁然开朗。土地平旷，屋舍俨然，有良田、美池、桑竹之属。阡陌交通，鸡犬相闻。其中往来种作，男女衣着，悉如外人。黄发垂髫，并怡然自乐。",
        "见渔人，乃大惊，问所从来。具答之。便要还家，设酒杀鸡作食。村中闻有此人，咸来问讯。自云先世避秦时乱，率妻子邑人来此绝境，不复出焉，遂与外人间隔。问今是何世，乃不知有汉，无论魏晋。此人一一为具言所闻，皆叹惋。余人各复延至其家，皆出酒食。停数日，辞去。此中人语云：“不足为外人道也。”",
        "既出，得其船，便扶向路，处处志之。及郡下，诣太守，说如此。太守即遣人随其往，寻向所志，遂迷，不复得路。",
        "南阳刘子骥，高尚士也，闻之，欣然规往。未果，寻病终。后遂无问津者。",
    ]),
    ("陋室铭", "刘禹锡", [
        "山不在高，有仙则名。水不在深，有龙则灵。斯是陋室，惟吾德馨。苔痕上阶绿，草色入帘青。谈笑有鸿儒，往来无白丁。可以调素琴，阅金经。无丝竹之乱耳，无案牍之劳形。南阳诸葛庐，西蜀子云亭。孔子云：何陋之有？",
    ]),
    ("爱莲说", "周敦颐", [
        "水陆草木之花，可爱者甚蕃。晋陶渊明独爱菊。自李唐来，世人甚爱牡丹。予独爱莲之出淤泥而不染，濯清涟而不妖，中通外直，不蔓不枝，香远益清，亭亭净植，可远观而不可亵玩焉。",
        "予谓菊，花之隐逸者也；牡丹，花之富贵者也；莲，花之君子者也。噫！菊之爱，陶后鲜有闻。莲之爱，同予者何人？牡丹之爱，宜乎众矣。",
    ]),
]

CSS = """body { margin: 0 1em; }
h1 { font-size: 1.4em; text-align: center; margin: 1em 0 0.2em; }
p.author { text-align: center; margin: 0 0 1em; }
p { text-indent: 2em; margin: 0 0 0.5em; text-align: justify; }
"""


def chapter(title, author, paragraphs):
    body = "\n".join(f"<p>{p}</p>" for p in paragraphs)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="zh-CN" lang="zh-CN">
<head><meta charset="utf-8"/><title>{title}</title><link rel="stylesheet" type="text/css" href="style.css"/></head>
<body>
<h1>{title}</h1>
<p class="author">{author}</p>
{body}
</body>
</html>
"""


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(root, "samples", "guwen.epub")
    os.makedirs(os.path.dirname(out), exist_ok=True)

    files = {"OEBPS/style.css": CSS}
    manifest, spine, nav = [], [], []
    for i, (title, author, paragraphs) in enumerate(TEXTS, 1):
        name = f"ch{i}.xhtml"
        files["OEBPS/" + name] = chapter(title, author, paragraphs)
        manifest.append(f'<item id="ch{i}" href="{name}" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="ch{i}"/>')
        nav.append(f'<li><a href="{name}">{title}</a></li>')

    files["OEBPS/nav.xhtml"] = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="zh-CN" lang="zh-CN">
<head><meta charset="utf-8"/><title>目录</title></head>
<body><nav epub:type="toc"><h1>目录</h1><ol>{"".join(nav)}</ol></nav></body>
</html>
"""
    files["OEBPS/content.opf"] = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id" xml:lang="zh-CN">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:identifier id="id">koreader-interlinear-pinyin-sample-guwen</dc:identifier>
<dc:title>古文三篇</dc:title>
<dc:language>zh-CN</dc:language>
<dc:creator>陶渊明 · 刘禹锡 · 周敦颐</dc:creator>
<dc:rights>Public domain</dc:rights>
<meta property="dcterms:modified">2026-11-08T00:00:00Z</meta>
</metadata>
<manifest>
<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
<item id="css" href="style.css" media-type="text/css"/>
{chr(10).join(manifest)}
</manifest>
<spine>{"".join(spine)}</spine>
</package>
"""
    container = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>
"""
    # Fixed timestamps so rebuilding gives an identical file.
    def info(name, compress):
        zi = zipfile.ZipInfo(name, date_time=(2026, 11, 8, 0, 0, 0))
        zi.compress_type = compress
        return zi

    with zipfile.ZipFile(out, "w") as z:
        z.writestr(info("mimetype", zipfile.ZIP_STORED), "application/epub+zip")
        z.writestr(info("META-INF/container.xml", zipfile.ZIP_DEFLATED), container)
        for name in sorted(files):
            z.writestr(info(name, zipfile.ZIP_DEFLATED), files[name])
    print(out)


if __name__ == "__main__":
    main()
