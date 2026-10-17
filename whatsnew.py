"""
"What's new": after an update, the app shows the patch notes for the versions you haven't seen yet.
The notes come from release-notes/<version>.md, bundled inside the app (the same files GitHub and
the website's Patch notes page use).
"""

import html
import os
import re

from rewind_core import APP_VERSION, RES, HERE


def _ver(s):
    return tuple(int(x) for x in re.findall(r"\d+", s or "")[:3]) or (0,)


def _folder():
    for base in (RES, HERE):
        p = os.path.join(base, "release-notes")
        if os.path.isdir(p):
            return p
    return ""


def md_to_html(text):
    """Just enough markdown for patch notes: bullet lists, **bold**, `code`, ## headings."""
    out, in_list = [], False
    for line in text.splitlines():
        line = line.rstrip()
        bare = re.sub(r"^\s*(?:[*-]\s+|#+\s*)", "", line).strip()   # drop the bullet or heading mark only
        esc = html.escape(bare)
        esc = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc)
        esc = re.sub(r"`(.+?)`", r"<code>\1</code>", esc)
        if re.match(r"^\s*[*-] ", line):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{esc}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if line.startswith("#"):
            out.append(f"<h4>{esc}</h4>")
        elif esc:
            out.append(f"<p>{esc}</p>")
    if in_list:
        out.append("</ul>")
    return "".join(out)


def unseen(last_seen, limit=5):
    """[(version, html)] for versions newer than last_seen, up to this one, newest first."""
    folder = _folder()
    if not folder:
        return []
    found = []
    for f in os.listdir(folder):
        m = re.fullmatch(r"(\d+\.\d+\.\d+)\.md", f)
        if m and _ver(last_seen) < _ver(m.group(1)) <= _ver(APP_VERSION):
            with open(os.path.join(folder, f), encoding="utf-8") as fh:
                found.append((m.group(1), md_to_html(fh.read())))
    found.sort(key=lambda x: _ver(x[0]), reverse=True)
    return found[:limit]
