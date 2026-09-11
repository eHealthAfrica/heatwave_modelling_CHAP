"""Export every generated DOCX and PPTX to PDF.

Two backends, picked at run time:

  Office COM (Windows, Word/PowerPoint installed) - preferred. The PDF is
  rendered by the same engine that renders the source file, so fonts, table
  banding and the theme colours match exactly instead of being approximated by
  a second layout engine.

  LibreOffice (`soffice --convert-to pdf`) - the fallback, and the only option
  in a Linux sandbox. It is a second layout engine, so treat its output as a
  proof rather than the final artefact: check the render, and say in your
  report that the PDF came from LibreOffice, not Office.

Either way the DOCX/PPTX is the source of truth. Ship it alongside the PDF.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

WD_FORMAT_PDF = 17
PP_FORMAT_PDF = 32


def _find_outroot():
    """Locate the outputs tree whether this sits in build/ or beside outputs/."""
    for cand in (os.path.join(HERE, "outputs"),
                 os.path.join(HERE, "..", "outputs"),
                 os.path.join(os.getcwd(), "outputs")):
        if os.path.isdir(cand):
            return os.path.normpath(cand)
    return os.path.normpath(os.path.join(HERE, ".."))


OUTROOT = _find_outroot()


def _abs(p):
    return os.path.abspath(p)


# --------------------------------------------------------------------------
# Backend detection
# --------------------------------------------------------------------------

def _soffice():
    """Path to a LibreOffice binary, or None."""
    for name in ("soffice", "libreoffice", "soffice.bin"):
        found = shutil.which(name)
        if found:
            return found
    for cand in (r"C:\Program Files\LibreOffice\program\soffice.exe",
                 r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
                 "/usr/bin/soffice", "/usr/bin/libreoffice",
                 "/Applications/LibreOffice.app/Contents/MacOS/soffice"):
        if os.path.isfile(cand):
            return cand
    return None


def _have_office():
    """True when Word and PowerPoint are drivable through COM."""
    if os.name != "nt":
        return False
    try:
        import win32com.client  # noqa: F401
        import pythoncom  # noqa: F401
    except ImportError:
        return False
    return True


# --------------------------------------------------------------------------
# Office COM backend
# --------------------------------------------------------------------------

def _com_convert(paths, app_id, opener, fmt):
    import pythoncom
    import win32com.client as win32

    pythoncom.CoInitialize()
    app = win32.DispatchEx(app_id)
    try:
        app.Visible = False
    except Exception:
        pass          # PowerPoint refuses to be hidden; harmless
    try:
        app.DisplayAlerts = 0
    except Exception:
        pass
    done = []
    try:
        for src in paths:
            dst = os.path.splitext(src)[0] + ".pdf"
            item = opener(app, _abs(src))
            try:
                item.SaveAs(_abs(dst), fmt)
                done.append(dst)
            finally:
                item.Close()
    finally:
        app.Quit()
        pythoncom.CoUninitialize()
    return done


def docx_to_pdf_com(paths):
    return _com_convert(
        paths, "Word.Application",
        lambda app, p: app.Documents.Open(p, ReadOnly=1),
        WD_FORMAT_PDF)


def pptx_to_pdf_com(paths):
    return _com_convert(
        paths, "PowerPoint.Application",
        lambda app, p: app.Presentations.Open(p, ReadOnly=1, WithWindow=False),
        PP_FORMAT_PDF)


# --------------------------------------------------------------------------
# LibreOffice backend
# --------------------------------------------------------------------------

def soffice_to_pdf(paths, binary):
    done = []
    for src in paths:
        outdir = os.path.dirname(_abs(src)) or "."
        cmd = [binary, "--headless", "--norestore",
               "--convert-to", "pdf", "--outdir", outdir, _abs(src)]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        dst = os.path.splitext(_abs(src))[0] + ".pdf"
        if os.path.isfile(dst):
            done.append(dst)
        else:
            print(f"  FAILED {os.path.basename(src)}: "
                  f"{(res.stderr or res.stdout).strip()[:300]}")
    return done


# --------------------------------------------------------------------------

def main(patterns=None):
    if patterns:
        docs = [p for p in patterns if p.lower().endswith(".docx")]
        decks = [p for p in patterns if p.lower().endswith(".pptx")]
    else:
        docs = sorted(glob.glob(os.path.join(OUTROOT, "**", "*.docx"),
                                recursive=True))
        decks = sorted(glob.glob(os.path.join(OUTROOT, "**", "*.pptx"),
                                 recursive=True))
    docs = [d for d in docs if not os.path.basename(d).startswith("~$")]
    decks = [d for d in decks if not os.path.basename(d).startswith("~$")]

    if not docs and not decks:
        print(f"Nothing to convert under {OUTROOT}")
        return []

    made = []
    if _have_office():
        print("Backend:    Microsoft Office (COM)")
        if docs:
            print(f"Word:       {len(docs)} file(s)")
            made += docx_to_pdf_com(docs)
        if decks:
            print(f"PowerPoint: {len(decks)} file(s)")
            made += pptx_to_pdf_com(decks)
    else:
        binary = _soffice()
        if not binary:
            print("No PDF backend available: neither Microsoft Office (COM) "
                  "nor LibreOffice was found.\n"
                  "The DOCX/PPTX are still the deliverable - ship those and "
                  "say the PDF could not be produced here.")
            return []
        print(f"Backend:    LibreOffice ({binary})")
        print("            Second layout engine - check the render before "
              "shipping, and say so in your report.")
        made += soffice_to_pdf(docs + decks, binary)

    for m in made:
        size = os.path.getsize(m) / 1024
        print(f"  {os.path.relpath(m, OUTROOT)}  ({size:,.0f} KB)")
    return made


if __name__ == "__main__":
    main(sys.argv[1:] or None)
