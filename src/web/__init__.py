"""ADIF website: public pages and the manufacturer portal over ADID, CDM and the gateway (D48, D52).

One FastAPI process serves three audiences from one registry and one access
policy:

* the **public** — landing page, registry lookup, product pages at the same
  ``/adid/{uuid}`` URI a QR code carries (HTML for browsers, JSON / JSON-LD for
  machines);
* **manufacturers** — a signed-in portal to upload, review, register, edit
  details (versioned) and manage versioned mapping templates;
* the **registry operator** and **authorities** — account approval, and access
  to restricted sections.

Server-rendered HTML (Jinja2) with plain CSS and JavaScript: no Node build step
and no external fonts or CDNs, so the artefact runs offline from one Python
install (NFR-1, NFR-9).
"""
