"""Render ANSI terminal output as an SVG 'screenshot' for the README.

    FORCE_COLOR=1 bash examples/demo.sh | python scripts/ansi2svg.py > docs/demo.svg
"""
import html
import re
import sys

PALETTE = {"31": "#ff6b6b", "32": "#5af78e", "33": "#f3f99d", "35": "#ff9cf5", "36": "#57c7ff", "2": "#7f8796"}
BG, FG = "#0d1117", "#e6edf3"


def spans(line):
    out, style, pos = [], set(), 0
    for m in re.finditer(r"\x1b\[([0-9;]*)m", line):
        if m.start() > pos:
            out.append((line[pos:m.start()], frozenset(style)))
        for code in (m.group(1) or "0").split(";"):
            if code == "0":
                style.clear()
            else:
                style.add(code)
        pos = m.end()
    out.append((line[pos:], frozenset(style)))
    return out


def main():
    lines = sys.stdin.read().rstrip("\n").split("\n")
    cw, lh, pad, top = 8.4, 19, 18, 44
    width = int(max(len(re.sub(r"\x1b\[[0-9;]*m", "", l)) for l in lines) * cw + pad * 2)
    height = int(top + len(lines) * lh + pad)
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
         f'<rect width="100%" height="100%" rx="10" fill="{BG}"/>',
         '<circle cx="22" cy="20" r="6" fill="#ff5f56"/><circle cx="42" cy="20" r="6" fill="#ffbd2e"/>'
         '<circle cx="62" cy="20" r="6" fill="#27c93f"/>',
         '<text font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="14" xml:space="preserve">']
    for i, line in enumerate(lines):
        y = top + i * lh
        o.append(f'<tspan x="{pad}" y="{y}">')
        for text, st in spans(line):
            if not text:
                continue
            fill = next((PALETTE[c] for c in ("31", "32", "33", "35", "36", "2") if c in st), FG)
            weight = ' font-weight="bold"' if "1" in st else ""
            o.append(f'<tspan fill="{fill}"{weight}>{html.escape(text)}</tspan>')
        o.append("</tspan>")
    o.append("</text></svg>")
    print("".join(o))


if __name__ == "__main__":
    main()
