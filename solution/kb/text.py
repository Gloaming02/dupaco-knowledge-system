"""Tokenising and chunking markdown pages into retrievable passages."""
import re

TOKEN = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)*%?|\$")
STOP = set("""a an and are as at be by can do does for from get give have how i if in is it me my
of on or our please tell the their there this to was what when where which who why will with you
your dupaco dupaco's s""".split())
_LINK = re.compile(r"!\[[^\]]*\]\([^)]*\)|\]\([^)]*\)")     # drop images and link targets
_WS = re.compile(r"\s+")


def _stem(t: str) -> str:
    # Prefix stemming: "recognition"/"recognized" -> "recogn", "employees"/"employee" -> "employ".
    # Crude but deterministic and cheap; numbers and short words are kept as they are.
    return t[:6] if len(t) > 6 and t.isalpha() else (t[:-1] if len(t) > 3 and t.endswith("s") and t.isalpha() else t)


def tokens(text: str) -> list[str]:
    return [_stem(t) for t in TOKEN.findall(text.lower()) if t not in STOP]


def clean(text: str) -> str:
    text = _LINK.sub("]", text).replace("[", "").replace("]", "")
    return _WS.sub(" ", text.replace("\\r\\n", " ").replace("<br>", " ")).strip()


def iter_blocks(markdown: str, title: str = ""):
    """Walk a page once, yielding
         ("para", heading, text)                       for prose
         ("row",  heading, label, header, cells)       for each table body row
    `heading` is the nearest markdown heading, `label` the short caption line above a table."""
    heading, label, para, header = title, "", [], None

    def flush():
        if para:
            t = clean(" ".join(para))
            para.clear()
            if len(t) > 20:
                return ("para", heading, t)
        return None

    for raw in markdown.splitlines():
        line = raw.strip()
        if line.startswith("|"):
            if (b := flush()):
                yield b
            cells = [clean(c) for c in line.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue                                    # separator row
            if header is None:
                header = cells
                continue
            yield ("row", heading, label, header, cells)
            continue
        header = None
        if line.startswith("#"):
            if (b := flush()):
                yield b
            heading, label = clean(line.lstrip("#")), ""
        elif not line:
            if (b := flush()):
                yield b
        else:
            if len(line) < 60 and not line.endswith((".", ":", "?", "!")) and not para:
                label = clean(line)                          # short caption above a table
            para.append(line)
    if (b := flush()):
        yield b


def row_text(heading: str, label: str, header: list, cells: list) -> str:
    pairs = [f"{h}: {c}" if h and h != c else c for h, c in zip(header, cells) if c]
    ctx = " / ".join(x for x in (heading, label) if x)
    return (f"{ctx} | " if ctx else "") + " | ".join(pairs)


def chunks(markdown: str, title: str = "") -> list[str]:
    """Paragraph chunks, plus one chunk per table row carrying its section label and header,
    so a row like '| 60 Month | 1.79% | 1.80% |' still knows it is a business certificate."""
    out, section, sec_head = [], [], None

    def close_section():
        # One extra passage per heading section, so lists and multi-paragraph answers
        # ("You're eligible to join if…" + bullet points) can be retrieved whole.
        if len(section) >= 2:
            body = " ".join(section)
            out.append(f"{sec_head}: {body}"[:900] if sec_head else body[:900])

    for b in iter_blocks(markdown, title):
        if b[0] == "para":
            _, heading, t = b
            if heading != sec_head:
                close_section()
                section, sec_head = [], heading
            section.append(t)
            out.append(f"{heading}: {t}" if heading and heading not in t else t)
        else:
            out.append(row_text(*b[1:]))
    close_section()
    return out
