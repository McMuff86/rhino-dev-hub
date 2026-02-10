# rhino-dev-hub — Projekt-Kontext

## Was ist dieses Repo?

Meta-Repository / Dashboard für das Rhino 3D Entwicklungs-Ökosystem von McMuff86. Enthält **keine eigentliche Software**, sondern:

- Eine zentrale Übersicht aller 27 Rhino-bezogenen Repos
- Ein Python-Script das via GitHub API Live-Daten fetcht und die README aktualisiert
- Eine GitHub Action die das wöchentlich automatisch ausführt

## Architektur

```
repos.yaml              ← Manuelle Metadaten (Kategorien, Rhino-Version, Status)
scripts/update_readme.py ← Fetcht GitHub API, merged mit yaml, schreibt README
README.md               ← Dashboard mit HTML-Comment-Markers für Auto-Update
.github/workflows/      ← Wöchentlicher Cron + Trigger bei repos.yaml Änderung
```

### Wie das Auto-Update funktioniert

1. `repos.yaml` definiert alle Repos mit manuellen Metadaten
2. `update_readme.py` holt via **GraphQL** (ein Call für alle Repos): Language, Last Commit, Description
3. Zusätzlich via **REST**: CI/Actions Status pro Repo
4. Manuelle Daten aus yaml haben Vorrang über API-Daten
5. Generierter Markdown wird zwischen `<!-- marker starts/ends -->` Kommentaren in die README eingefügt

### Marker-System

Die README hat drei auto-aktualisierte Bereiche:
- `<!-- overview starts/ends -->` — Repo-Count, Sprachen, Stats
- `<!-- repos starts/ends -->` — Kategorie-Tabellen mit allen Repos
- `<!-- updated starts/ends -->` — Timestamp

Alles ausserhalb der Marker (Intro, Mermaid-Diagramm) ist statisch.

## Häufige Aufgaben

### Neues Repo hinzufügen
1. Eintrag in `repos.yaml` unter `repos:` hinzufügen
2. Kategorie wählen (oder neue unter `categories:` anlegen)
3. Pushen — GitHub Action aktualisiert README automatisch

### Repo entfernen
1. Eintrag aus `repos.yaml` löschen
2. Pushen

### Kategorie hinzufügen
1. Neue Kategorie unter `categories:` in `repos.yaml` mit `title` und `icon`
2. Repos dieser Kategorie zuweisen

### Mermaid-Diagramm aktualisieren
Das Diagramm in `README.md` ist **statisch** (nicht auto-generiert). Beziehungen manuell im `graph LR` Block pflegen.

### Lokal testen
```bash
pip install -r scripts/requirements.txt
GITHUB_TOKEN=$(gh auth token) python scripts/update_readme.py
# Oder ohne CI-Check (schneller):
GITHUB_TOKEN=$(gh auth token) python scripts/update_readme.py --skip-ci
```

## Konventionen

- **Sprache Code:** Englisch
- **Sprache Dokumentation/UI:** Deutsch
- **Commit Messages:** Conventional Commits (`feat:`, `fix:`, `docs:`)
- **repos.yaml Felder:**
  - `category` — Muss einer definierten Kategorie entsprechen
  - `maturity` — `active` | `maintained` | `experimental` | `archived`
  - `rhino_version` — `7/8`, `8`, oder `N/A`
  - `private: true` — Für private Repos (werden ohne Link angezeigt)
  - `relates_to` — Liste verwandter Repos (für Mermaid-Diagramm Referenz)

## Abhängigkeiten

- Python 3.12+
- `requests` — HTTP Client für GitHub API
- `pyyaml` — YAML Parser für repos.yaml
- `GITHUB_TOKEN` — Environment Variable (optional lokal, automatisch in GitHub Actions)

## Fallstricke

- Private Repos erscheinen nicht in der GraphQL-Antwort → werden nur aus yaml-Daten angezeigt
- Das Mermaid-Diagramm muss manuell gepflegt werden wenn sich Beziehungen ändern
- Die GitHub Action triggered **nicht** bei README-Änderungen (Loop-Schutz), nur bei `repos.yaml`
- `rh_caminterface_v2` und `RhinoTextExtractor` liefern manchmal keine Language via API (leeres Repo oder nur Config-Files)
