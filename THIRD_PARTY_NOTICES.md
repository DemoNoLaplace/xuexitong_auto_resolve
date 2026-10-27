# Third-Party Notices

This project depends on the following third-party packages. Their licenses apply
to the corresponding components and to binary distributions that bundle them.

| Component | License | Project |
| --- | --- | --- |
| requests | Apache-2.0 | https://github.com/psf/requests |
| beautifulsoup4 | MIT | https://www.crummy.com/software/BeautifulSoup/ |
| lxml | BSD-3-Clause | https://lxml.de/ |
| PyMuPDF | AGPL-3.0 or Artifex Commercial License | https://github.com/pymupdf/PyMuPDF |
| uiautomation | Apache-2.0 | https://github.com/yinkaisheng/Python-UIAutomation-for-Windows |
| numpy | BSD-3-Clause | https://numpy.org/ |
| Pillow | HPND | https://python-pillow.org/ |
| fonttools | MIT | https://github.com/fonttools/fonttools |

## Important: PyMuPDF / AGPL

PyMuPDF is dual-licensed under the GNU Affero General Public License v3.0
(AGPL-3.0) or a commercial license from Artifex. If you distribute a binary
that bundles PyMuPDF, you are responsible for complying with the applicable
license. The source code of this project is published, but that does not by
itself satisfy every AGPL obligation for a bundled binary. For commercial or
closed-source distribution, obtain an appropriate PyMuPDF license.

## Font reference data

`chaoxing_flow/font_ref.npz` is a generated glyph-signature database used to
recognize the `font-cxsecret` obfuscation font. It was generated from
**Noto Sans SC Regular** (a Source Han Sans / Noto Sans CJK family font),
which is licensed under the SIL Open Font License, Version 1.1.

- Noto fonts: https://github.com/notofonts/noto-cjk
- SIL OFL 1.1: see `LICENSES/OFL-1.1.txt`

The database contains numeric raster signatures, not the original font files.
