"""Tokenising and chunking markdown pages into retrievable passages."""
import re

TOKEN = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)*%?|\$")
STOP = set("""a an and are as at be by can do does for from get give have how i if in is it me my
of on or our please tell the their there this to was what when where which who why will with you
your dupaco dupaco's s""".split())
_LINK = re.compile(r"!\[[^\]]*\]\([^)]*\)|\]\([^)]*\)")     # drop images and link targets
_WS = re.compile(r"\s+")


def tokens(text: str) -> list[str]:
    return [t for t in TOKEN.findall(text.lower()) if t not in STOP]


def clean(text: str) -> str:
    text = _LINK.sub("]", text).replace("[", "").replace("]", "")
    return _WS.sub(" ", text.replace("\\r\\n", " ").replace("<br>", " ")).strip()


def chunks(markdown: str, title: str = "") -> list[str]:
    """Paragraph chunks, plus one chunk per table row carrying its section label and header,
    so a row like '| 60 Month | 1.79% | 1.80% |' still knows it is a business certificate."""
    out, heading, label, para = [], title, "", []
    header = None

    def flush():
        if para:
            t = clean(" ".join(para))
            if len(t) > 20:
                out.append(f"{heading}: {t}" if heading and heading not in t else t)
            para.clear()

    for raw in markdown.splitlines():
        line = raw.strip()
        if line.startswith("|"):
            flush()
            cells = [clean(c) for c in line.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue                                    # separator row
            if header is None:
                header = cells
                continue
            pairs = [f"{h}: {c}" if h and h != c else c for h, c in zip(header, cells) if c]
            ctx = " / ".join(x for x in (heading, label) if x)
            out.append(f"{ctx} | " + " | ".join(pairs) if ctx else " | ".join(pairs))
            continue
        header = None
        if line.startswith("#"):
            flush()
            heading, label = clean(line.lstrip("#")), ""
        elif not line:
            flush()
        else:
            if len(line) < 60 and not line.endswith((".", ":", "?", "!")) and not para:
                label = clean(line)                          # short caption above a table
            para.append(line)
    flush()
    return out
